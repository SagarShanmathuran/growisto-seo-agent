"""
Adapts our gap_analyzer + ahrefs_csv_loader outputs into the dict/DataFrame
shape that the existing word_report.generate_word_report and
strategic_advisor.build_strategic_recommendations expect.

This is the bridge between the new (CSV-based) data layer and the legacy
report generator.
"""

from urllib.parse import urlparse

import pandas as pd

from .ahrefs_csv_loader import SiteData
from .gap_analyzer import GapAnalysis


def _domain(url_or_name: str) -> str:
    parsed = urlparse(url_or_name if "://" in url_or_name else f"https://{url_or_name}")
    return parsed.netloc.replace("www.", "") or url_or_name


def build_keyword_gaps_df(gap: GapAnalysis) -> pd.DataFrame:
    """
    Page-level traffic-opportunity table (replaces opportunity_score with the
    competitor's actual monthly traffic from each keyword — what they ACTUALLY win).
    """
    rows = []
    for g in gap.gap_keywords:
        rows.append({
            "keyword":            g.keyword,
            "search_volume":      g.volume,
            "competitor":         g.best_competitor,
            "competitor_position": g.competitor_rank,
            "competitor_traffic": g.competitor_traffic,   # actual win, not theoretical volume
            "competitor_url":     g.competitor_url,
            "client_position":    "Not ranking" if g.client_rank == "NR" else g.client_rank,
        })
    return pd.DataFrame(rows)


def build_low_hanging_fruit_df(client: SiteData, max_rows: int = 30) -> pd.DataFrame:
    """Client ranks 11–30 — close to page 1, push to top 10 for quick wins."""
    nb = client.nb_keywords
    pos = nb["Current position"]
    lhf = nb[(pos >= 11) & (pos <= 30) & (nb["Volume"] >= 1000)].copy()
    lhf = lhf.sort_values("Volume", ascending=False).head(max_rows)

    rows = []
    for _, r in lhf.iterrows():
        vol = int(r["Volume"])
        traffic_top5 = int(vol * 0.15)  # rough: top 5 captures ~15% of volume
        priority = round((vol * 100) / max(int(r["Current position"]), 1), 1)
        rows.append({
            "keyword": r["Keyword"],
            "current_position": int(r["Current position"]),
            "search_volume": vol,
            "traffic_if_top5": traffic_top5,
            "priority_score": priority,
        })
    return pd.DataFrame(rows)


def build_top_competitor_pages_df(competitors: list[SiteData], max_rows: int = 20) -> pd.DataFrame:
    """Highest-traffic pages across all competitors."""
    frames = []
    for comp in competitors:
        pg = comp.pages.copy()
        pg["competitor"] = comp.name
        frames.append(pg)
    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values("Traffic", ascending=False).head(max_rows)

    rows = []
    for _, r in merged.iterrows():
        rows.append({
            "competitor":  r["competitor"],
            "url":         r["URL"],
            "traffic":     int(r["Traffic"]),
            "top_keyword": r.get("Top keyword", ""),
        })
    return pd.DataFrame(rows)


def build_keyword_ranking_comparison_df(
    client: SiteData,
    competitors: list[SiteData],
    *,
    max_rows: int = 15,
    min_volume: int = 1000,
) -> pd.DataFrame:
    """
    Side-by-side ranking comparison for top high-volume keywords.

    Shape:
        Keyword | Volume | <client name> | <comp 1> | <comp 2> | <comp 3>
        each cell is the rank position or 'NR'

    Selection: take the union of top-volume keywords across all sites
    (covers both client's strengths and gaps).
    """
    # Collect candidate keywords by max volume seen across all sites.
    # Skip junk: keywords with no letters (e.g. just digits) or length < 3.
    import re as _re
    candidates: dict[str, int] = {}
    for site in [client, *competitors]:
        nb = site.nb_keywords[site.nb_keywords["Volume"] >= min_volume]
        for _, r in nb.iterrows():
            kw = str(r["Keyword"]).strip()
            if len(kw) < 3 or not _re.search(r"[A-Za-zऀ-ॿ஀-௿]", kw):
                continue   # require at least one letter (ASCII or Indic)
            v = int(r["Volume"])
            if v > candidates.get(kw, 0):
                candidates[kw] = v

    # Sort by volume desc, take top N
    top_kws = sorted(candidates.items(), key=lambda x: -x[1])[:max_rows]

    # Build rank lookups per site
    def _rank_lookup(site: SiteData) -> dict:
        m = {}
        for _, r in site.nb_keywords.iterrows():
            pos = r["Current position"]
            if pd.notna(pos):
                m[r["Keyword"]] = int(pos)
        return m

    client_ranks = _rank_lookup(client)
    comp_ranks = [(c.name, _rank_lookup(c)) for c in competitors]

    rows = []
    for kw, vol in top_kws:
        row = {"Keyword": kw, "Volume": vol}
        cr = client_ranks.get(kw)
        row[f"{client.name} (★)"] = str(cr) if cr is not None else "NR"
        for cname, lookup in comp_ranks:
            r = lookup.get(kw)
            row[cname] = str(r) if r is not None else "NR"
        rows.append(row)
    return pd.DataFrame(rows)


def build_page_traffic_comparison_df(
    client: SiteData,
    competitors: list[SiteData],
    *,
    max_rows: int = 12,
) -> pd.DataFrame:
    """
    Page-level traffic comparison — for each top competitor page, find the
    equivalent client page (matched by top keyword) and show side-by-side.

    Shape:
        Top Keyword | Volume | Client Page Traffic | <comp 1> Traffic | <comp 2> Traffic | <comp 3> Traffic
    """
    # Use the union of top pages across competitors as candidates
    all_top: list[tuple[str, str, int]] = []  # (top_keyword, url, traffic)
    for comp in competitors:
        pg = comp.pages.copy().sort_values("Traffic", ascending=False).head(20)
        for _, r in pg.iterrows():
            kw = str(r.get("Top keyword", "") or "").strip()
            if kw:
                all_top.append((kw, str(r.get("URL", "")), int(r["Traffic"])))

    # Group by top_keyword (the same keyword often has competing pages on multiple sites)
    by_kw: dict[str, int] = {}
    for kw, _url, traffic in all_top:
        if traffic > by_kw.get(kw, 0):
            by_kw[kw] = traffic

    top_kws = sorted(by_kw.items(), key=lambda x: -x[1])[:max_rows]

    # Lookup: per site, what's the traffic for a page whose top keyword == X?
    def _site_pages_by_top_kw(site: SiteData) -> dict[str, tuple[int, str]]:
        m: dict[str, tuple[int, str]] = {}
        for _, r in site.pages.iterrows():
            kw = str(r.get("Top keyword", "") or "").strip()
            if not kw: continue
            traffic = int(r.get("Traffic", 0))
            url = str(r.get("URL", ""))
            if traffic > m.get(kw, (0, ""))[0]:
                m[kw] = (traffic, url)
        return m

    client_pages = _site_pages_by_top_kw(client)
    comp_pages = [(c.name, _site_pages_by_top_kw(c)) for c in competitors]

    # Volume lookup from client+competitor keyword data (whoever has it)
    vol_lookup: dict[str, int] = {}
    for site in [client, *competitors]:
        for _, r in site.nb_keywords.iterrows():
            kw = r["Keyword"]
            v = int(r["Volume"])
            if v > vol_lookup.get(kw, 0):
                vol_lookup[kw] = v

    rows = []
    for kw, _ in top_kws:
        client_traffic, client_url = client_pages.get(kw, (0, ""))
        row = {
            "Top Keyword":              kw,
            "Volume":                   vol_lookup.get(kw, 0),
            f"{client.name} (★)":      f"{client_traffic:,}" if client_traffic else "—",
        }
        for cname, lookup in comp_pages:
            t, _u = lookup.get(kw, (0, ""))
            row[cname] = f"{t:,}" if t else "—"
        rows.append(row)
    return pd.DataFrame(rows)


def build_ahrefs_dict(client: SiteData, competitors: list[SiteData], gap: GapAnalysis) -> dict:
    """Produces the `ahrefs` dict word_report.generate_word_report expects."""
    return {
        "keyword_gaps":            build_keyword_gaps_df(gap),
        "low_hanging_fruit":       build_low_hanging_fruit_df(client),
        "top_comp_pages":          build_top_competitor_pages_df(competitors),
        "keyword_rank_comparison": build_keyword_ranking_comparison_df(client, competitors),
        "page_traffic_comparison": build_page_traffic_comparison_df(client, competitors),
        "big_wins":                gap.big_wins,
        "client_total_traffic":    client.nb_traffic,
    }


def build_comp_traffic_dict(competitors: list[SiteData]) -> dict:
    """Maps competitor display name -> non-brand monthly traffic."""
    return {c.name: c.nb_traffic for c in competitors}


if __name__ == "__main__":
    from .ahrefs_csv_loader import load
    from .gap_analyzer import analyze

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
    gap = analyze(client, comps)
    ahrefs = build_ahrefs_dict(client, comps, gap)
    print("keyword_gaps:", ahrefs["keyword_gaps"].shape, list(ahrefs["keyword_gaps"].columns))
    print("low_hanging_fruit:", ahrefs["low_hanging_fruit"].shape)
    print("top_comp_pages:", ahrefs["top_comp_pages"].shape)
    print("client_total_traffic:", ahrefs["client_total_traffic"])
    print("\nTop 5 gaps:\n", ahrefs["keyword_gaps"].head().to_string(index=False))
    print("\nTop 5 LHF:\n", ahrefs["low_hanging_fruit"].head().to_string(index=False))
    print("\nTop 5 pages:\n", ahrefs["top_comp_pages"].head().to_string(index=False))
