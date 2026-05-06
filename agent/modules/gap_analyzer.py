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
class BigWin:
    keyword:            str
    volume:             int
    competitor_traffic: int    # actual monthly clicks the competitor wins from this keyword
    competitor:         str
    competitor_url:     str
    client_rank:        str
    score:              float
    pitch:              str    # one-line analyst-friendly summary


@dataclass
class GapAnalysis:
    client_name:    str
    client_summary: dict
    competitors:    list[dict]      = field(default_factory=list)
    traffic_ratio:  float           = 0.0   # client_traffic / avg_competitor_traffic
    gap_keywords:   list[GapKeyword] = field(default_factory=list)
    gap_total_volume: int           = 0
    big_wins:       list[BigWin]    = field(default_factory=list)   # top-3 concrete opportunities
    achievable_top10_traffic: int   = 0     # sum of competitor traffic from top 10 RELEVANT gap kws — the realistic short-term target
    saturated_keywords: list[dict]  = field(default_factory=list)  # client already top-10, growth-limited
    page_count_delta: int           = 0     # avg_competitor_pages - client_pages
    notes:          list[str]       = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


_NON_SERVICE_URL_RE = __import__("re").compile(
    r"/(blog|blogs|glossary|insights|resources|guide|guides|news|articles|"
    r"learn|help|support|careers|press|about|library|webinar|ebook|whitepaper)/",
    __import__("re").I,
)


def _is_b2b(business_model: str) -> bool:
    bm = (business_model or "").lower()
    return bm.startswith("b2b") or bm in ("financial", "saas")


def _is_ecomm(business_model: str) -> bool:
    bm = (business_model or "").lower()
    return bm.startswith("b2c") or bm in ("ecommerce", "retail")


def _should_filter_intent(business_model: str) -> bool:
    """Both B2B and B2C ecomm benefit from intent filtering — informational
    keywords inflate the gap-volume number with traffic the client can't realistically
    capture (you can't out-rank a 10-year-old wirecutter listicle as a brand)."""
    return _is_b2b(business_model) or _is_ecomm(business_model)


def _filter_keywords_by_intent(df, business_model: str):
    """Restrict to commercial+transactional intent (drop info/nav/local)."""
    if not _should_filter_intent(business_model):
        return df
    # Ahrefs CSVs have these as boolean columns
    has_intent_cols = "Commercial" in df.columns and "Transactional" in df.columns
    if not has_intent_cols:
        return df
    return df[(df["Commercial"] == True) | (df["Transactional"] == True)].copy()


def _filter_blog_urls(df, business_model: str, url_col: str = "Current URL"):
    """Drop keywords ranking from blog/help/resources URLs — only count
    service/category/product pages."""
    if not _should_filter_intent(business_model) or url_col not in df.columns:
        return df
    mask = df[url_col].fillna("").astype(str).apply(lambda u: not bool(_NON_SERVICE_URL_RE.search(u)))
    return df[mask].copy()


# Stopwords kept short — only obviously generic words that don't carry topic signal.
_TOPIC_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on", "at",
    "by", "from", "as", "is", "are", "be", "this", "that", "your", "our", "we",
    "us", "you", "best", "top", "buy", "shop", "online", "near", "me", "near me",
    "free", "cheap", "price", "prices", "cost", "review", "reviews", "vs",
    "how", "what", "where", "when", "why", "which", "who",
    # Common e-comm filler
    "set", "sets", "kit", "pack", "size", "sizes", "type", "types",
    # Generic intent suffixes
    "tool", "tools", "platform", "software", "software for", "service", "services",
    "company", "companies", "brand", "brands",
})


# Tokens that appear so often in client vocabularies that single-token match is meaningless
# (e.g. "cat" appears in millions of unrelated kws — "norwegian forest cat" shouldn't pass
# just because the client sells cat litter). Single occurrences of these don't count as
# evidence of relevance — but multi-token matches involving them do.
_GENERIC_VERTICAL_TOKENS = frozenset({
    "cat", "cats", "dog", "dogs", "pet", "pets", "puppy", "puppies", "kitten", "kittens",
    "baby", "babies", "kid", "kids", "child", "children", "men", "women", "girl", "girls",
    "boy", "boys", "home", "house", "office", "kitchen", "bathroom", "bedroom",
    "online", "shop", "store", "buy", "best", "top", "new", "free", "cheap",
    "indian", "india", "usa", "uk",
})


def _client_topic_tokens(client_keywords: __import__("pandas").DataFrame, top_n: int = 200) -> tuple[set[str], set[str]]:
    """
    Build the client's "category vocabulary" from their top-traffic non-brand keywords.
    Returns (specific_tokens, generic_tokens) — specific = product/category words that
    define the client's catalog uniquely; generic = vertical words that are too broad
    to use as a single-token relevance signal.

    e.g. for Catalyst Pet (cat litter brand):
         specific = {litter, natural, pellet, fragrance, ...}
         generic  = {cat, pet, ...}
    """
    import re as _re
    if client_keywords is None or len(client_keywords) == 0:
        return set(), set()

    sort_col = "Current organic traffic" if "Current organic traffic" in client_keywords.columns else "Volume"
    top = client_keywords.sort_values(sort_col, ascending=False).head(top_n)

    token_counts: dict[str, int] = {}
    for kw in top["Keyword"].astype(str):
        toks = _re.findall(r"[a-zA-Zऀ-ॿ஀-௿]+", kw.lower())
        for t in toks:
            if len(t) < 3 or t in _TOPIC_STOPWORDS:
                continue
            token_counts[t] = token_counts.get(t, 0) + 1

    # Keep tokens appearing ≥2 times. Split into generic-vertical vs specific.
    all_tokens = {tok for tok, cnt in token_counts.items() if cnt >= 2}
    generic = all_tokens & _GENERIC_VERTICAL_TOKENS
    specific = all_tokens - _GENERIC_VERTICAL_TOKENS
    return specific, generic


def _is_relevant_to_client(keyword: str, specific: set[str], generic: set[str]) -> bool:
    """
    Stricter relevance: a competitor keyword passes if it shares EITHER:
      - 1+ SPECIFIC token (e.g. 'litter', 'kadai') — strong signal
      - 2+ tokens in total when only generic-vertical matches exist
        (so "norwegian forest cat" with only 1 generic token "cat" → rejected;
         "cat litter" with 1 generic + 1 specific → accepted via specific)

    This is what stops "norwegian forest cat" / "orange cat" / "burmese cat" from
    passing for a cat-litter brand whose vocabulary contains "cat" + "litter".
    """
    if not specific and not generic:
        return True   # no signal — include everything

    import re as _re
    toks = _re.findall(r"[a-zA-Zऀ-ॿ஀-௿]+", str(keyword).lower())
    meaningful = {t for t in toks if len(t) >= 3 and t not in _TOPIC_STOPWORDS}

    if meaningful & specific:
        return True   # any specific match → relevant

    # Only generic matches — require 2+ overlapping generics, AND at least one of
    # those generic matches must form a 2-word phrase with another non-stopword
    # in the keyword. Practically: one-word matches with just 'cat' fail.
    generic_overlap = meaningful & generic
    if len(generic_overlap) >= 2:
        return True

    return False


def _filter_relevance(df, specific: set[str], generic: set[str]):
    """Drop competitor keywords that don't pass the relevance test."""
    if not specific and not generic:
        return df
    mask = df["Keyword"].astype(str).apply(lambda k: _is_relevant_to_client(k, specific, generic))
    return df[mask].copy()


def analyze(
    client: SiteData,
    competitors: list[SiteData],
    *,
    min_gap_volume: int = 3000,
    max_gap_keywords: int = 30,
    saturated_top_n: int = 15,
    business_model: str = "",
) -> GapAnalysis:
    """Run the full gap analysis a senior analyst would perform manually.

    For B2B clients (`business_model` starts with 'b2b' or is 'financial'/'saas'),
    the analysis restricts keywords to commercial/transactional intent and excludes
    blog/help/resources URLs — because for B2B, only service-page rankings on
    transactional intent drive leads. Even 50-100 monthly clicks on a service page
    can be valuable due to high deal AOV.
    """
    if not competitors:
        return GapAnalysis(client.name, client.summary(), notes=["No competitors provided"])

    is_b2b = _is_b2b(business_model)
    intent_filter_on = _should_filter_intent(business_model)

    # Lower the volume floor for B2B — transactional keywords are usually low-volume but high-intent.
    if is_b2b:
        min_gap_volume = min(min_gap_volume, 200)
    elif intent_filter_on:
        # Ecomm: still allow lower-volume commercial keywords through (e.g. specific SKU searches)
        min_gap_volume = min(min_gap_volume, 500)

    # Filter client + competitor keywords to commercial/transactional intent (excl. blog/info URLs)
    if intent_filter_on:
        client_nb = _filter_blog_urls(_filter_keywords_by_intent(client.nb_keywords, business_model),
                                       business_model)
        comp_filtered = []
        for c in competitors:
            cnb_filtered = _filter_blog_urls(_filter_keywords_by_intent(c.nb_keywords, business_model),
                                              business_model)
            comp_filtered.append((c, cnb_filtered))
    else:
        client_nb = client.nb_keywords
        comp_filtered = [(c, c.nb_keywords) for c in competitors]

    # ── Catalog-relevance filter ───────────────────────────────────────────
    # Build the client's category vocabulary from their actual ranked keywords,
    # split into specific (product terms — strong signal) and generic-vertical
    # (cat/pet/dog — single-token match is meaningless for these). A competitor
    # keyword passes if it shares 1+ specific token, OR 2+ generic-vertical tokens.
    # This stops 'norwegian forest cat' / 'orange cat' (informational breed kws)
    # from passing for a cat-LITTER brand whose vocab is {cat, litter, ...}.
    specific_tokens, generic_tokens = _client_topic_tokens(client_nb)
    client_tokens = specific_tokens | generic_tokens   # back-compat, used in some checks below
    if specific_tokens or generic_tokens:
        comp_filtered = [(c, _filter_relevance(cnb, specific_tokens, generic_tokens)) for c, cnb in comp_filtered]

    # Use FILTERED traffic (intent + relevance) for the headline ratio.
    # This is what makes the "X× larger" number actually achievable — we only
    # count traffic competitors get on keywords the client could realistically
    # compete for given their existing catalog.
    use_filtered = intent_filter_on or bool(client_tokens)
    client_signal_traffic = (
        int(client_nb["Current organic traffic"].sum()) if use_filtered and not client_nb.empty
        else client.nb_traffic
    )
    avg_comp_signal_traffic = (
        sum(int(cnb["Current organic traffic"].sum()) for _, cnb in comp_filtered) / len(comp_filtered)
        if use_filtered and comp_filtered
        else sum(c.nb_traffic for c in competitors) / len(competitors)
    )
    traffic_ratio = (client_signal_traffic / avg_comp_signal_traffic) if avg_comp_signal_traffic else 0.0

    avg_comp_pages = sum(c.page_count for c in competitors) / len(competitors)
    page_delta = int(avg_comp_pages - client.page_count)

    client_ranks = dict(zip(client_nb["Keyword"], client_nb["Current position"]))

    # Gap keywords: any competitor ranks top 10, client NR or rank > 20
    # For B2B, the comp.nb_keywords has been pre-filtered to transactional/commercial + service pages
    gap_rows: dict[str, GapKeyword] = {}
    for comp, cnb in comp_filtered:
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

    # ── Big-Win Opportunities ──────────────────────────────────────────────
    # Score each gap keyword by a "real-world impact" metric instead of raw volume.
    # We weight competitor's ACTUAL captured traffic heavily (proves intent) and
    # boost low-hanging-fruit cases (client ranks 11-30, push to top 5).
    def _score_big_win(g: GapKeyword) -> float:
        # Competitor's real traffic is the single best signal — they're winning
        # this many clicks from this keyword on their actual page.
        score = g.competitor_traffic * 1.0
        # Prefer wins where competitor isn't dominating (top-1 fights are hard)
        if g.competitor_rank > 1: score *= 1.2
        if g.competitor_rank > 3: score *= 1.1
        # Bonus when client is partially ranking (LHF) — easier to win than NR
        if g.client_rank != "NR":
            try:
                if 11 <= int(g.client_rank) <= 30:
                    score *= 1.3
            except ValueError:
                pass
        return score

    big_wins = []
    if gap_rows:
        scored = sorted(gap_rows.values(), key=_score_big_win, reverse=True)
        for g in scored[:3]:
            score = _score_big_win(g)
            # Build an analyst-friendly pitch line
            if g.client_rank == "NR":
                pitch = (
                    f"Build a page on '{g.keyword}' (vol {g.volume:,}/mo). "
                    f"{g.best_competitor} captures {g.competitor_traffic:,} clicks/mo from this — "
                    f"copy their structure at {g.competitor_url}"
                )
            else:
                pitch = (
                    f"Push '{g.keyword}' from rank {g.client_rank} to top 5. "
                    f"{g.best_competitor} (rank {g.competitor_rank}) wins {g.competitor_traffic:,} clicks/mo here."
                )
            big_wins.append(BigWin(
                keyword=g.keyword, volume=g.volume,
                competitor_traffic=g.competitor_traffic,
                competitor=g.best_competitor, competitor_url=g.competitor_url,
                client_rank=g.client_rank, score=round(score, 1), pitch=pitch,
            ))

    gap_list = sorted(gap_rows.values(), key=lambda x: -x.volume)[:max_gap_keywords]
    gap_total_vol = sum(g.volume for g in gap_list)

    # ── Achievable target: sum of competitor traffic from the top-10 BIG-WIN
    # opportunities (already filtered by relevance). This is what the analyst
    # would realistically aim to capture in 6-12 months — NOT the inflated
    # "competitor's total traffic minus client's total traffic" headline.
    if gap_rows:
        top_10_by_score = sorted(gap_rows.values(), key=_score_big_win, reverse=True)[:10]
        achievable_top10_traffic = sum(g.competitor_traffic for g in top_10_by_score)
    else:
        achievable_top10_traffic = 0

    # Saturated: client already top 10 (limited growth upside) — uses filtered client_nb for B2B
    sat = client_nb[client_nb["Current position"] <= 10].sort_values(
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
    intent_label = "transactional/commercial" if intent_filter_on else "non-brand"

    if is_b2b:
        # B2B framing: clicks on service pages with commercial/transactional intent
        notes.append(
            f"📊 B2B view: client has {len(client_nb)} {intent_label} keyword(s) on service pages "
            f"({client_signal_traffic:,} clicks/mo). Total non-brand traffic ({client.nb_traffic:,}) "
            f"includes blog/info traffic that does not convert to leads."
        )
        if len(client_nb) < 10:
            notes.append(
                f"⚠ Client ranks for almost no commercial-intent keywords on service pages "
                f"— this is the actual SEO problem to solve. Build dedicated service/feature/pricing pages."
            )
    elif intent_filter_on:
        # Ecomm framing: transactional traffic on category/product pages only
        info_excluded = client.nb_traffic - client_signal_traffic
        if info_excluded > 0 and client.nb_traffic > 0:
            pct_info = info_excluded / client.nb_traffic * 100
            notes.append(
                f"📊 Filtered to transactional/commercial intent: client has {len(client_nb)} buyer-intent "
                f"keyword(s) ({client_signal_traffic:,} clicks/mo). Excluded {info_excluded:,} info/blog "
                f"clicks ({pct_info:.0f}%) — those don't convert to purchases."
            )

    # Catalog-relevance note — what got filtered as out-of-category
    if specific_tokens or generic_tokens:
        unfiltered_avg = sum(c.nb_traffic for c in competitors) / len(competitors)
        if avg_comp_signal_traffic > 0 and unfiltered_avg > avg_comp_signal_traffic:
            irrelevant_pct = (1 - avg_comp_signal_traffic / unfiltered_avg) * 100
            top_specific = ", ".join(sorted(specific_tokens)[:8]) or "(none — all generic vertical terms)"
            top_generic = ", ".join(sorted(generic_tokens)[:5])
            notes.append(
                f"🎯 Relevance filter — specific catalog tokens: {top_specific}. "
                f"Generic vertical tokens: {top_generic}. Required 1+ specific match OR 2+ generic. "
                f"Excluded {irrelevant_pct:.0f}% of competitor traffic as out-of-category."
            )

    if traffic_ratio < 0.25:
        gap_label = f"{intent_label} traffic" if is_b2b else "traffic"
        notes.append(f"Client gets only {traffic_ratio*100:.0f}% of avg competitor {gap_label} — large gap")
    elif traffic_ratio < 0.5:
        notes.append(f"Client gets {traffic_ratio*100:.0f}% of avg competitor {intent_label} traffic — moderate gap")
    elif traffic_ratio < 1.0:
        notes.append(f"Client gets {traffic_ratio*100:.0f}% of avg competitor {intent_label} traffic — small gap")
    else:
        notes.append(f"Client outranks competitor average — limited room to grow")

    if page_delta > 100:
        notes.append(f"Competitors average {page_delta} more pages — clear catalog/category expansion scope")

    if gap_total_vol >= 500_000:
        notes.append(f"Massive gap-keyword opportunity: {gap_total_vol:,} monthly search volume across {len(gap_list)} keywords")
    elif gap_total_vol >= 100_000:
        notes.append(f"Significant gap-keyword opportunity: {gap_total_vol:,} monthly volume")
    elif is_b2b and gap_total_vol >= 5_000:
        notes.append(
            f"B2B gap-keyword opportunity: {gap_total_vol:,} monthly volume on commercial intent. "
            f"For B2B, even 50-100 clicks on service pages is meaningful given high deal AOV."
        )

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
        big_wins=big_wins,
        achievable_top10_traffic=achievable_top10_traffic,
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
