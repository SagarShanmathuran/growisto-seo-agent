"""
ROI estimation — incremental-traffic method (Growisto's actual approach).

Logic:
    incremental_traffic = max(0, target_traffic − client_current_traffic)
    incremental_revenue = incremental_traffic × CVR × AOV
    ROI multiple        = annual_incremental_revenue / annual_retainer_cost

`target_traffic` is the analyst's estimate of where the client's traffic could
realistically be 6-12 months in. Sensible defaults from competitor data:
    - Top competitor traffic    → aggressive
    - Average competitor traffic → realistic
    - Lowest competitor traffic  → conservative
"""


def calculate_roi(
    client_current_traffic: int = 0,
    target_traffic: int = 0,
    *,
    aov: float = 2000,
    conversion_rate: float = 0.01,
    monthly_seo_cost: float = 150_000,
    # Legacy kwargs — kept for backward compatibility with old callers
    competitor_traffic: int | None = None,
    achievable_fraction: float = 0.10,
) -> dict:
    """
    Returns the incremental-traffic ROI breakdown.

    Modern call (preferred):
        calculate_roi(client_current_traffic=35000, target_traffic=200000,
                      aov=2000, conversion_rate=0.01, monthly_seo_cost=150_000)

    Legacy call (still works — uses 10% of competitor_traffic as target):
        calculate_roi(competitor_traffic=600000)
    """
    # Legacy compatibility — derive target from competitor total if needed
    if target_traffic <= 0 and competitor_traffic is not None:
        target_traffic = int(competitor_traffic * achievable_fraction)

    incremental_traffic = max(0, target_traffic - client_current_traffic)
    incremental_orders  = int(incremental_traffic * conversion_rate)
    monthly_revenue     = round(incremental_orders * aov, 2)
    annual_revenue      = round(monthly_revenue * 12, 2)
    annual_cost         = round(monthly_seo_cost * 12, 2)

    if annual_cost > 0 and monthly_revenue > 0:
        roi_multiple   = round(annual_revenue / annual_cost, 2)
        roi_pct        = round((annual_revenue - annual_cost) / annual_cost * 100, 1)
        payback_months = round(annual_cost / monthly_revenue, 1)
    else:
        roi_multiple, roi_pct, payback_months = 0.0, -100.0, None

    # Viability tiers (matches Growisto's mental model):
    #   ≥ 2x  → strong (worth pitching)
    #   ≥ 1x  → marginal (case-by-case)
    #   < 1x  → weak (skip)
    if roi_multiple >= 2.0:
        viability = "strong";   is_viable = True
    elif roi_multiple >= 1.0:
        viability = "marginal"; is_viable = True
    else:
        viability = "weak";     is_viable = False

    return {
        "client_current_traffic": client_current_traffic,
        "target_traffic":         target_traffic,
        "incremental_traffic":    incremental_traffic,
        "incremental_orders":     incremental_orders,
        "monthly_revenue":        monthly_revenue,
        "annual_revenue":         annual_revenue,
        "annual_seo_cost":        annual_cost,
        "monthly_seo_cost":       monthly_seo_cost,
        "roi_multiple":           roi_multiple,
        "roi_pct":                roi_pct,
        "payback_months":         payback_months,
        "viability":              viability,
        "is_viable":              is_viable,
        "aov":                    aov,
        "conversion_rate":        conversion_rate,
        # Legacy keys for word_report.py back-compat
        "competitor_traffic":     competitor_traffic if competitor_traffic else target_traffic,
        "achievable_traffic":     incremental_traffic,
        "monthly_orders":         incremental_orders,
        "roi_ratio":              roi_multiple,
    }


def calculate_roi_scenarios(
    client_current_traffic: int,
    competitor_traffics: list[int],
    *,
    aov: float = 2000,
    conversion_rate: float = 0.01,
    monthly_seo_cost: float = 150_000,
) -> dict:
    """Compute conservative / realistic / aggressive scenarios from competitor traffic."""
    if not competitor_traffics:
        return {"error": "No competitor traffic provided"}

    sorted_t = sorted(competitor_traffics)
    conservative = sorted_t[0]                                              # lowest comp
    realistic    = int(sum(competitor_traffics) / len(competitor_traffics))  # avg
    aggressive   = sorted_t[-1]                                              # highest comp

    return {
        "conservative": calculate_roi(client_current_traffic, conservative,
                                       aov=aov, conversion_rate=conversion_rate,
                                       monthly_seo_cost=monthly_seo_cost),
        "realistic":    calculate_roi(client_current_traffic, realistic,
                                       aov=aov, conversion_rate=conversion_rate,
                                       monthly_seo_cost=monthly_seo_cost),
        "aggressive":   calculate_roi(client_current_traffic, aggressive,
                                       aov=aov, conversion_rate=conversion_rate,
                                       monthly_seo_cost=monthly_seo_cost),
    }
