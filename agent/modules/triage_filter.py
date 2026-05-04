"""
Pre-analysis triage. Decides whether a site is worth the analyst's full ~30min
review, or can be auto-rejected as LOW potential.

Implements the "IIT B" learnings — but model-aware (B2B sites with low traffic
are NOT auto-skipped, since contract value can justify SEO).

Flow:
  1. Detect business model
  2. Sample sitemap → page count + AOV (B2C) or service signals (B2B)
  3. Apply model-specific thresholds
  4. Return: keep | review | reject + reasons
"""

from dataclasses import dataclass, asdict, field

from .business_model_detector import detect as detect_model, BusinessModel
from .aov_extractor import extract_aov


@dataclass
class TriageResult:
    decision:       str           # "keep" | "review" | "reject"
    business_model: str
    confidence:     float
    page_count:     int           # from sitemap
    aov:            float | None
    currency:       str | None
    reasons:        list[str]     = field(default_factory=list)
    flags:          list[str]     = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def triage(client_url: str, *, deep: bool = True) -> TriageResult:
    """
    `deep=True` runs AOV extraction + sitemap walk (slow, ~30s).
    `deep=False` only runs business model detection (fast, ~5s) — use for first-pass screening.
    """
    bm = detect_model(client_url)

    page_count = 0
    aov = None
    currency = None
    reasons: list[str] = []
    flags: list[str] = []

    if bm.primary == "unknown":
        return TriageResult(
            decision="review",
            business_model=bm.primary,
            confidence=bm.confidence,
            page_count=0,
            aov=None,
            currency=None,
            reasons=["Could not determine business model — manual review required"],
            flags=["fetch_failed_or_unclear_signals"],
        )

    # AOV / page count probe (B2C only — B2B doesn't need this)
    is_b2c = bm.primary == "b2c_ecommerce"
    if deep and is_b2c:
        aov_result = extract_aov(client_url, sample_size=10)
        page_count = aov_result.get("products_found", 0)
        # Use recommended_aov (handles long-tail luxury skew) rather than raw median
        aov = aov_result.get("recommended_aov") or aov_result.get("median_aov")
        currency = aov_result.get("currency")

    # Decision tree — model-aware
    if is_b2c:
        if page_count < 30 and aov is not None and aov < 500:
            return TriageResult(
                decision="reject",
                business_model=bm.primary,
                confidence=bm.confidence,
                page_count=page_count,
                aov=aov,
                currency=currency,
                reasons=[
                    f"Thin catalog ({page_count} products) AND low AOV ({currency} {aov:.0f})",
                    "Even strong SEO ranking won't deliver sufficient revenue to justify retainer",
                ],
                flags=["thin_catalog", "low_aov"],
            )
        if page_count < 30:
            flags.append("thin_catalog")
            reasons.append(f"Thin catalog ({page_count} products) — limited new-page creation scope")
        if aov is not None and aov < 500:
            flags.append("low_aov")
            reasons.append(f"Low AOV ({currency} {aov:.0f}) — needs subscription/LTV signal to justify")
        if not reasons:
            aov_str = f"{aov:.0f}" if aov else "unknown"
            reasons.append(f"B2C ecommerce, {page_count} products, AOV {currency or '?'} {aov_str} — proceed to full analysis")

    elif bm.primary in ("b2b_saas", "financial", "b2b_services"):
        # B2B: low traffic OK if it has demo/pricing/contact signals
        if not (bm.has_pricing or bm.has_demo):
            flags.append("no_demo_no_pricing")
            reasons.append("No pricing/demo/contact-sales pages detected — site may be too immature for SEO")
        else:
            reasons.append(f"{bm.primary.upper()} with {'pricing' if bm.has_pricing else ''} {'+ demo' if bm.has_demo else ''} — strong B2B SEO target despite traffic level")

    else:  # unknown
        reasons.append("Unclear business model — recommend analyst review")

    decision = "keep"
    if "thin_catalog" in flags and "low_aov" in flags:
        decision = "reject"
    elif "no_demo_no_pricing" in flags:
        decision = "review"

    return TriageResult(
        decision=decision,
        business_model=bm.primary,
        confidence=bm.confidence,
        page_count=page_count,
        aov=aov,
        currency=currency,
        reasons=reasons,
        flags=flags,
    )


if __name__ == "__main__":
    import sys, json
    urls = sys.argv[1:] or ["vinodcookware.com", "adbrew.io", "mayorgacoffee.com"]
    for url in urls:
        print(f"\n=== {url} ===")
        result = triage(url)
        print(json.dumps(result.to_dict(), indent=2))
