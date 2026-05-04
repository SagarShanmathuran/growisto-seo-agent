"""
SEO metrics scoring.

Each check returns 0–100.  Weights sum to 100.
SEO Health Score  = weighted average of all checks (100 = perfect).
Outreach Potential = inverse: more issues → higher potential → better lead.
"""

from dataclasses import dataclass, field
from typing import Any


# ── individual checks ─────────────────────────────────────────────────────────

def _score_https(d: dict) -> float:
    return 100.0 if d.get("uses_https") else 0.0


def _score_load_time(d: dict) -> float:
    t = d.get("load_time_s", 99)
    if t < 1:   return 100.0
    if t < 2:   return 80.0
    if t < 3:   return 55.0
    if t < 5:   return 30.0
    return 0.0


def _score_redirects(d: dict) -> float:
    n = d.get("redirect_count", 0)
    if n == 0:  return 100.0
    if n == 1:  return 70.0
    return 30.0


def _score_title(d: dict) -> float:
    length = d.get("title_len", 0)
    if length == 0:         return 0.0
    if 30 <= length <= 60:  return 100.0
    if 20 <= length <= 70:  return 70.0
    return 40.0


def _score_meta_desc(d: dict) -> float:
    length = d.get("meta_desc_len", 0)
    if length == 0:           return 0.0
    if 120 <= length <= 160:  return 100.0
    if length > 0:            return 60.0
    return 0.0


def _score_h1(d: dict) -> float:
    count = d.get("h1_count", 0)
    if count == 1:   return 100.0
    if count == 0:   return 0.0
    return 40.0   # multiple H1s is bad


def _score_headings(d: dict) -> float:
    h2 = d.get("h2_count", 0)
    h3 = d.get("h3_count", 0)
    if h2 >= 2:         return 100.0
    if h2 == 1:         return 70.0
    if h3 > 0:          return 40.0
    return 0.0


def _score_images(d: dict) -> float:
    total = d.get("img_count", 0)
    if total == 0:
        return 80.0   # no images — neutral-ish
    no_alt = d.get("img_no_alt", 0)
    ratio  = (total - no_alt) / total
    return round(ratio * 100, 1)


def _score_word_count(d: dict) -> float:
    wc = d.get("word_count", 0)
    if wc >= 1000:  return 100.0
    if wc >= 500:   return 80.0
    if wc >= 300:   return 60.0
    if wc >= 100:   return 30.0
    return 0.0


def _score_canonical(d: dict) -> float:
    return 100.0 if d.get("canonical") else 0.0


def _score_sitemap(d: dict) -> float:
    return 100.0 if d.get("sitemap_exists") else 0.0


def _score_robots(d: dict) -> float:
    return 100.0 if d.get("robots_txt_exists") else 0.0


def _score_schema(d: dict) -> float:
    return 100.0 if d.get("has_schema") else 0.0


def _score_og(d: dict) -> float:
    return 100.0 if d.get("has_og") else 0.0


def _score_viewport(d: dict) -> float:
    return 100.0 if d.get("has_viewport") else 0.0


# ── weighted spec ─────────────────────────────────────────────────────────────

@dataclass
class _Check:
    key:    str
    label:  str
    fn:     Any
    weight: float   # must sum to 100 across all checks


_CHECKS: list[_Check] = [
    _Check("https",      "HTTPS",              _score_https,      8),
    _Check("load_time",  "Page load time",     _score_load_time,  8),
    _Check("redirects",  "Redirect chain",     _score_redirects,  3),
    _Check("title",      "Title tag",          _score_title,     10),
    _Check("meta_desc",  "Meta description",   _score_meta_desc, 10),
    _Check("h1",         "H1 tag",             _score_h1,         8),
    _Check("headings",   "Heading structure",  _score_headings,   5),
    _Check("images",     "Image alt text",     _score_images,     7),
    _Check("word_count", "Content length",     _score_word_count, 7),
    _Check("canonical",  "Canonical tag",      _score_canonical,  5),
    _Check("sitemap",    "Sitemap.xml",        _score_sitemap,    8),
    _Check("robots",     "Robots.txt",         _score_robots,     5),
    _Check("schema",     "Structured data",    _score_schema,     8),
    _Check("og",         "Open Graph tags",    _score_og,         5),
    _Check("viewport",   "Mobile viewport",    _score_viewport,   3),
]

assert abs(sum(c.weight for c in _CHECKS) - 100) < 0.01, "Weights must sum to 100"


# ── public API ────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    key:    str
    label:  str
    score:  float   # 0-100
    weight: float


@dataclass
class MetricsResult:
    checks:            list[CheckResult] = field(default_factory=list)
    health_score:      float = 0.0   # 0-100  (higher = better optimised)
    potential_score:   float = 0.0   # 0-100  (higher = more room to improve)
    potential_level:   str   = "LOW"
    recommend_outreach: bool = False

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.score < 60]

    @property
    def passed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.score >= 80]


class MetricsCalculator:
    """Score crawled page data and derive outreach potential."""

    def calculate(self, page_data: dict[str, Any]) -> MetricsResult:
        if "error" in page_data:
            return MetricsResult()

        results: list[CheckResult] = []
        weighted_sum = 0.0

        for chk in _CHECKS:
            score = chk.fn(page_data)
            results.append(CheckResult(chk.key, chk.label, score, chk.weight))
            weighted_sum += score * (chk.weight / 100)

        health      = round(weighted_sum, 1)
        potential   = round(100 - health, 1)

        if potential >= 55:
            level, outreach = "HIGH", True
        elif potential >= 30:
            level, outreach = "MEDIUM", True
        else:
            level, outreach = "LOW", False

        return MetricsResult(
            checks=results,
            health_score=health,
            potential_score=potential,
            potential_level=level,
            recommend_outreach=outreach,
        )
