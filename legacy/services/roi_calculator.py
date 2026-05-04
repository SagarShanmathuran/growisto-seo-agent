"""SEO ROI estimation based on competitor traffic and client AOV."""


def calculate_roi(
    competitor_traffic: int,
    achievable_fraction: float = 0.10,
    aov: float = 50.0,
    conversion_rate: float = 0.02,
    monthly_seo_cost: float = 1500.0,
    target_traffic: int = 0,
) -> dict:
    """
    If target_traffic is set (> 0), use it directly as the achievable traffic.
    Otherwise fall back to competitor_traffic × achievable_fraction (10% default).
    """
    achievable_traffic = target_traffic if target_traffic > 0 else int(competitor_traffic * achievable_fraction)
    monthly_orders      = int(achievable_traffic * conversion_rate)
    monthly_revenue     = round(monthly_orders * aov, 2)
    annual_revenue      = round(monthly_revenue * 12, 2)
    annual_cost         = round(monthly_seo_cost * 12, 2)

    if annual_cost > 0:
        roi_ratio = round(annual_revenue / annual_cost, 2)
        roi_pct   = round((annual_revenue - annual_cost) / annual_cost * 100, 1)
    else:
        roi_ratio, roi_pct = 0.0, 0.0

    return {
        "competitor_traffic":  competitor_traffic,
        "achievable_traffic":  achievable_traffic,
        "monthly_orders":      monthly_orders,
        "monthly_revenue":     monthly_revenue,
        "annual_revenue":      annual_revenue,
        "annual_seo_cost":     annual_cost,
        "roi_ratio":           roi_ratio,
        "roi_pct":             roi_pct,
        "is_viable":           roi_ratio >= 3.0,
    }
