"""Generate prioritised SEO recommendations from metrics results."""

from typing import Any
from .metrics import MetricsResult, CheckResult


_PRIORITY_MAP = {
    "https":      "Critical",
    "title":      "High",
    "meta_desc":  "High",
    "h1":         "High",
    "sitemap":    "High",
    "load_time":  "High",
    "schema":     "Medium",
    "images":     "Medium",
    "canonical":  "Medium",
    "headings":   "Medium",
    "word_count": "Medium",
    "robots":     "Medium",
    "og":         "Low",
    "viewport":   "Low",
    "redirects":  "Low",
}

_PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _advice(chk: CheckResult, page: dict[str, Any]) -> str:
    key = chk.key

    if key == "https":
        return "Migrate to HTTPS — browsers mark HTTP sites as 'Not Secure', hurting trust and rankings."

    if key == "load_time":
        t = page.get("load_time_s", "?")
        return (
            f"Page loads in {t}s — aim for under 2s. "
            "Compress images, enable caching, minify CSS/JS."
        )

    if key == "redirects":
        n = page.get("redirect_count", 0)
        return f"{n} redirect(s) detected — each adds latency. Consolidate to a single canonical URL."

    if key == "title":
        length = page.get("title_len", 0)
        if length == 0:
            return "No <title> tag found — add one (30-60 characters) with the target keyword."
        return f"Title is {length} chars — optimal range is 30-60. {'Shorten it.' if length > 60 else 'Expand it.'}"

    if key == "meta_desc":
        length = page.get("meta_desc_len", 0)
        if length == 0:
            return "Meta description is missing — add one (120-160 chars) to improve click-through rate."
        return f"Meta description is {length} chars — keep it between 120-160 characters."

    if key == "h1":
        count = page.get("h1_count", 0)
        if count == 0:
            return "No H1 tag found — add one clear H1 with the primary keyword."
        return f"{count} H1 tags found — each page should have exactly one H1."

    if key == "headings":
        return "Content lacks H2/H3 subheadings — use them to structure content and help search engines understand topics."

    if key == "images":
        no_alt = page.get("img_no_alt", 0)
        return f"{no_alt} image(s) missing alt text — add descriptive alt attributes for accessibility and image SEO."

    if key == "word_count":
        wc = page.get("word_count", 0)
        return f"Homepage has only {wc} words — thin content. Aim for at least 500 words of relevant content."

    if key == "canonical":
        return "No canonical tag — add <link rel='canonical'> to prevent duplicate content issues."

    if key == "sitemap":
        return "No sitemap.xml found — create one and submit it in Google Search Console."

    if key == "robots":
        return "No robots.txt found — add one to guide crawlers and reference your sitemap."

    if key == "schema":
        return "No structured data (Schema.org) detected — add JSON-LD markup to enable rich results in search."

    if key == "og":
        return "No Open Graph tags — add og:title, og:description, og:image for better social sharing previews."

    if key == "viewport":
        return "Missing viewport meta tag — add <meta name='viewport' content='width=device-width, initial-scale=1'> for mobile friendliness."

    return f"Improve {chk.label}."


class RecommendationEngine:
    """Turn a MetricsResult into a prioritised recommendation list."""

    def generate(
        self,
        metrics: MetricsResult,
        page_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        Returns recommendations only for checks that scored below 80,
        sorted Critical → High → Medium → Low.
        """
        recs = []
        for chk in metrics.checks:
            if chk.score >= 80:
                continue
            priority = _PRIORITY_MAP.get(chk.key, "Low")
            recs.append({
                "check":          chk.key,
                "category":       chk.label,
                "current_score":  f"{chk.score:.0f}/100",
                "priority":       priority,
                "recommendation": _advice(chk, page_data),
            })

        recs.sort(key=lambda r: _PRIORITY_ORDER.get(r["priority"], 9))
        return recs
