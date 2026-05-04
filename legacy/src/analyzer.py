"""
SEO Potential Analyzer — pure Python, no external APIs.

Orchestrates crawling → scoring → recommendations for one or many websites,
then returns structured results suitable for reporting or JSON export.
"""

from dataclasses import dataclass, field, asdict
from typing import Any
from urllib.parse import urlparse

from .crawler import WebCrawler
from .metrics import MetricsCalculator, MetricsResult
from .recommendations import RecommendationEngine


@dataclass
class SiteResult:
    domain:             str
    url:                str
    health_score:       float
    potential_score:    float
    potential_level:    str         # HIGH / MEDIUM / LOW
    recommend_outreach: bool
    key_signals:        dict        = field(default_factory=dict)
    recommendations:    list[dict]  = field(default_factory=list)
    error:              str | None  = None

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(raw: str) -> str:
    raw = raw.strip().lower()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def _key_signals(page: dict[str, Any], mr: MetricsResult) -> dict:
    """Pluck the most useful signals for the report summary."""
    return {
        "uses_https":       page.get("uses_https"),
        "load_time_s":      page.get("load_time_s"),
        "title_len":        page.get("title_len"),
        "meta_desc_len":    page.get("meta_desc_len"),
        "h1_count":         page.get("h1_count"),
        "word_count":       page.get("word_count"),
        "img_no_alt":       page.get("img_no_alt"),
        "has_sitemap":      page.get("sitemap_exists"),
        "has_robots":       page.get("robots_txt_exists"),
        "has_schema":       page.get("has_schema"),
        "has_og":           page.get("has_og"),
        "has_viewport":     page.get("has_viewport"),
        "redirect_count":   page.get("redirect_count"),
        "checks_failed":    len(mr.failed_checks),
        "checks_passed":    len(mr.passed_checks),
    }


class SEOAnalyzer:
    """
    Analyse websites for SEO outreach potential.

    Usage::

        analyzer = SEOAnalyzer()
        result   = analyzer.analyze("example.com")
        results  = analyzer.analyze_batch(["a.com", "b.com"])
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._crawler  = WebCrawler(cfg.get("crawler", {}))
        self._metrics  = MetricsCalculator()
        self._recs     = RecommendationEngine()

    # ── public ────────────────────────────────────────────────────────────────

    def analyze(self, url: str) -> SiteResult:
        """Analyse a single URL and return a SiteResult."""
        url    = _clean(url)
        domain = urlparse(url).netloc.replace("www.", "")

        page = self._crawler.crawl(url)

        if "error" in page:
            return SiteResult(
                domain=domain, url=url,
                health_score=0, potential_score=100,
                potential_level="UNKNOWN",
                recommend_outreach=False,
                error=page["error"],
            )

        mr   = self._metrics.calculate(page)
        recs = self._recs.generate(mr, page)

        return SiteResult(
            domain=domain,
            url=url,
            health_score=mr.health_score,
            potential_score=mr.potential_score,
            potential_level=mr.potential_level,
            recommend_outreach=mr.recommend_outreach,
            key_signals=_key_signals(page, mr),
            recommendations=recs,
        )

    def analyze_batch(self, urls: list[str], verbose: bool = False) -> list[SiteResult]:
        """Analyse multiple URLs sequentially."""
        results = []
        for url in urls:
            display = url.replace("https://", "").replace("http://", "")
            print(f"  🔍  Analysing {display} …", end=" ", flush=True)
            r = self.analyze(url)
            if verbose:
                print(f"health={r.health_score}  potential={r.potential_score}  [{r.potential_level}]")
            else:
                icon = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "❄️"}.get(r.potential_level, "?")
                print(f"{icon} {r.potential_level}")
            results.append(r)
        return results
