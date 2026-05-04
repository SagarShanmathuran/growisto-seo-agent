"""
Compares client SiteData against a list of competitor SiteData objects.
Produces the structured signals an analyst would write up:
  - traffic gap vs competitors
  - high-value gap keywords (comp ranks top 10, client doesn't)
  - saturated keywords (client already top 10)
  - traffic trends
  - page count delta
"""

from dataclasses import dataclass, asdict, field
import pandas as pd

from .ahrefs_csv_loader import SiteData


@dataclass
class GapKeyword:
    keyword:           str
    volume:            int
    best_competitor:   str
    competitor_rank:   int
    competitor_traffic: int     # actual monthly traffic the competitor's page gets from this keyword
    competitor_url:    str      # competitor's ranking URL — useful for "copy this page"
    client_rank:       str      # 'NR' or int as string


@dataclass
class GapAnalysis:
    client_name:    str
    client_summary: dict
    competitors:    list[dict]      = field(default_factory=list)
    traffic_ratio:  float           = 0.0   # client_traffic / avg_competitor_traffic
    gap_keywords:   list[GapKeyword] = field(default_factory=list)
    gap_total_volume: int           = 0
    saturated_keywords: list[dict]  = field(default_factory=list)  # client already top-10, growth-limited
    page_count_delta: int           = 0     # avg_competitor_pages - client_pages
    notes:          list[str]       = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def analyze(
    client: SiteData,
    competitors: list[SiteData],
    *,
    min_gap_volume: int = 3000,
    max_gap_keywords: int = 30,
    saturated_top_n: int = 15,
) -> GapAnalysis:
    """Run the full gap analysis a senior analyst would perform manually."""
    if not competitors:
        return GapAnalysis(client.name, client.summary(), notes=["No competitors provided"])

    avg_comp_traffic = sum(c.nb_traffic for c in competitors) / len(competitors)
    traffic_ratio = (client.nb_traffic / avg_comp_traffic) if avg_comp_traffic else 0.0

    avg_comp_pages = sum(c.page_count for c in competitors) / len(competitors)
    page_delta = int(avg_comp_pages - client.page_count)

    client_ranks = dict(zip(client.nb_keywords["Keyword"], client.nb_keywords["Current position"]))

    # Gap keywords: any competitor ranks top 10, client NR or rank > 20
    gap_rows: dict[str, GapKeyword] = {}
    for comp in competitors:
        cnb = comp.nb_keywords
        top10c = cnb[(cnb["Current position"] <= 10) & (cnb["Volume"] >= min_gap_volume)]
        for _, row in top10c.iterrows():
            kw = row["Keyword"]
            client_rank_val = client_ranks.get(kw)
            client_rank_n = client_rank_val if pd.notna(client_rank_val) else 999
            if client_rank_n <= 20:
                continue
            comp_rank = int(row["Current position"])
            existing = gap_rows.get(kw)
            if existing and existing.competitor_rank <= comp_rank:
                continue
            comp_traffic = int(row.get("Current organic traffic", 0) or 0)
            comp_url = str(row.get("Current URL", "") or "")
            gap_rows[kw] = GapKeyword(
                keyword=kw,
                volume=int(row["Volume"]),
                best_competitor=comp.name,
                competitor_rank=comp_rank,
                competitor_traffic=comp_traffic,
                competitor_url=comp_url,
                client_rank="NR" if client_rank_n == 999 else str(int(client_rank_n)),
            )

    gap_list = sorted(gap_rows.values(), key=lambda x: -x.volume)[:max_gap_keywords]
    gap_total_vol = sum(g.volume for g in gap_list)

    # Saturated: client already top 10 (limited growth upside)
    sat = client.nb_keywords[client.nb_keywords["Current position"] <= 10].sort_values(
        "Volume", ascending=False
    ).head(saturated_top_n)
    saturated = [
        {
            "keyword": r["Keyword"],
            "volume": int(r["Volume"]),
            "rank": int(r["Current position"]),
            "current_traffic": int(r["Current organic traffic"]),
        }
        for _, r in sat.iterrows()
    ]

    notes = []
    if traffic_ratio < 0.25:
        notes.append(f"Client gets only {traffic_ratio*100:.0f}% of avg competitor traffic — large gap")
    elif traffic_ratio < 0.5:
        notes.append(f"Client gets {traffic_ratio*100:.0f}% of avg competitor traffic — moderate gap")
    elif traffic_ratio < 1.0:
        notes.append(f"Client gets {traffic_ratio*100:.0f}% of avg competitor traffic — small gap")
    else:
        notes.append(f"Client outranks competitor average — limited room to grow")

    if page_delta > 100:
        notes.append(f"Competitors average {page_delta} more pages — clear catalog/category expansion scope")

    if gap_total_vol >= 500_000:
        notes.append(f"Massive gap-keyword opportunity: {gap_total_vol:,} monthly search volume across {len(gap_list)} keywords")
    elif gap_total_vol >= 100_000:
        notes.append(f"Significant gap-keyword opportunity: {gap_total_vol:,} monthly volume")

    if client.traffic_change < -5000:
        notes.append(f"Client traffic declining ({client.traffic_change:+,}) — needs attention")
    declining_comps = [c.name for c in competitors if c.traffic_change < -5000]
    if declining_comps:
        notes.append(f"Competitors losing traffic: {', '.join(declining_comps)} — favorable timing")

    return GapAnalysis(
        client_name=client.name,
        client_summary=client.summary(),
        competitors=[c.summary() for c in competitors],
        traffic_ratio=round(traffic_ratio, 3),
        gap_keywords=gap_list,
        gap_total_volume=gap_total_vol,
        saturated_keywords=saturated,
        page_count_delta=page_delta,
        notes=notes,
    )


if __name__ == "__main__":
    import sys, json
    from .ahrefs_csv_loader import load

    base = "../"
    client = load("Vinod Cookware",
        f"{base}vinodcookware.com-organic-keywords-subdomai_2026-04-12_22-26-06.csv",
        f"{base}vinodcookware.com-top-pages-subdomains-in-_2026-04-12_22-25-32.csv")
    comps = [
        load("Milton",
            f"{base}www.milton.in-organic-keywords-subdomains-i_2026-04-12_22-27-43.csv",
            f"{base}www.milton.in-top-pages-subdomains-in--act_2026-04-12_22-27-36.csv"),
        load("Borosil",
            f"{base}myborosil.com-organic-keywords-subdomains-i_2026-04-12_22-28-25.csv",
            f"{base}myborosil.com-top-pages-subdomains-in--act_2026-04-12_22-28-11.csv"),
        load("TTK Prestige",
            f"{base}shop.ttkprestige.com-organic-keywords-subdo_2026-04-12_22-29-35.csv",
            f"{base}shop.ttkprestige.com-top-pages-subdomains-i_2026-04-12_22-29-18.csv"),
    ]
    result = analyze(client, comps)
    out = result.to_dict()
    out["gap_keywords"] = [asdict(g) for g in result.gap_keywords][:10]
    print(json.dumps(out, indent=2, default=str))
