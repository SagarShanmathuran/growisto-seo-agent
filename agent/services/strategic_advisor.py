"""Generate big-picture strategic SEO recommendations from analysis data."""

import pandas as pd
import re


def _extract_category(url: str) -> str:
    """Pull the first meaningful path segment from a URL."""
    url = re.sub(r"https?://(www\.)?", "", url).strip("/")
    parts = [p for p in url.split("/") if p and not p.startswith("?")]
    return parts[1].replace("-", " ").title() if len(parts) > 1 else parts[0].replace("-", " ").title() if parts else ""


def build_strategic_recommendations(ahrefs: dict, site_result=None) -> list[dict]:
    """
    Returns up to 5 strategic recommendations, each with:
      title, priority, rationale, actions (list of strings)
    """
    gaps_df  = ahrefs.get("keyword_gaps",      pd.DataFrame())
    lh_df    = ahrefs.get("low_hanging_fruit",  pd.DataFrame())
    tp_df    = ahrefs.get("top_comp_pages",     pd.DataFrame())
    recs = []

    # ── 1. Create New Pages ───────────────────────────────────────────────────
    new_page_actions = []
    if not gaps_df.empty:
        top_gaps = gaps_df.head(5)
        for _, row in top_gaps.iterrows():
            kw  = row.get("keyword", "")
            vol = row.get("search_volume", 0)
            new_page_actions.append(
                f'Create a dedicated page targeting **"{kw}"** '
                f'(vol: {int(vol):,}/mo, competitor ranks #{int(row.get("competitor_position", 0))})'
            )
    if not tp_df.empty and len(new_page_actions) < 5:
        seen = set()
        for _, row in tp_df.iterrows():
            kw = row.get("top_keyword", "")
            if kw and kw not in seen:
                seen.add(kw)
                new_page_actions.append(
                    f'Replicate competitor page on **"{kw}"** '
                    f'({row.get("competitor","")} gets {int(row.get("traffic",0)):,}/mo from it)'
                )
            if len(new_page_actions) >= 5:
                break

    if new_page_actions:
        recs.append({
            "title":    "Create New Pages",
            "priority": "High",
            "rationale": (
                f"{len(gaps_df)} keyword gaps identified where competitors rank top 20 "
                f"and client has no presence. Each gap is a missed traffic opportunity."
                if not gaps_df.empty else
                "Competitors have high-traffic pages on topics the client doesn't cover yet."
            ),
            "actions": new_page_actions,
        })

    # ── 2. Optimize Existing Pages to Increase Traffic ────────────────────────
    lh_actions = []
    if not lh_df.empty:
        for _, row in lh_df.head(5).iterrows():
            kw  = row.get("keyword", "")
            pos = row.get("current_position", "?")
            vol = row.get("search_volume", 0)
            est = row.get("traffic_if_top5", 0)
            lh_actions.append(
                f'**"{kw}"** — currently pos {pos}, vol {int(vol):,}/mo. '
                f'Pushing to top 5 could add ~{int(est):,} visits/mo.'
            )

    if lh_actions:
        recs.append({
            "title":    "Optimize Existing Pages to Increase Traffic",
            "priority": "High",
            "rationale": (
                f"{len(lh_df)} pages rank positions 11–30 — they're close to page 1 "
                "but getting almost zero clicks. Small improvements deliver fast results."
            ),
            "actions": lh_actions,
        })

    # ── 3. Content Categories to Improve ─────────────────────────────────────
    cat_actions = []
    if not tp_df.empty:
        cat_traffic: dict[str, int] = {}
        for _, row in tp_df.iterrows():
            cat = _extract_category(str(row.get("url", "")))
            if cat:
                cat_traffic[cat] = cat_traffic.get(cat, 0) + int(row.get("traffic", 0))

        top_cats = sorted(cat_traffic.items(), key=lambda x: -x[1])[:5]
        for cat, trf in top_cats:
            cat_actions.append(
                f'**{cat}** category — competitors collectively earn ~{trf:,} visits/mo from this topic area.'
            )

    if not gaps_df.empty and not gaps_df.get("keyword", pd.Series()).empty:
        theme_counts: dict[str, int] = {}
        for kw in gaps_df.get("keyword", pd.Series()).dropna():
            first_word = str(kw).split()[0] if kw else ""
            if first_word:
                theme_counts[first_word] = theme_counts.get(first_word, 0) + 1
        top_themes = sorted(theme_counts.items(), key=lambda x: -x[1])[:3]
        for theme, count in top_themes:
            if count > 1:
                cat_actions.append(
                    f'**"{theme}…" keyword cluster** — {count} gap keywords share this theme; build a content hub around it.'
                )

    if cat_actions:
        recs.append({
            "title":    "Content Categories to Improve",
            "priority": "Medium",
            "rationale": (
                "Competitor traffic is concentrated in specific content categories. "
                "Building depth in these areas signals topical authority to Google."
            ),
            "actions": cat_actions[:5],
        })

    # ── 4. Optimize On-Page Content ────────────────────────────────────────────
    onpage_actions = [
        "Add the primary target keyword in the H1, first paragraph, and meta title of each page.",
        "Expand thin pages to 800+ words with supporting subtopics (H2/H3 structure).",
        "Add FAQ sections to target featured snippet opportunities for informational keywords.",
        "Optimize meta titles and descriptions with clear CTAs to improve click-through rate.",
        "Add structured data (Schema.org) to product/article pages for rich result eligibility.",
    ]
    if site_result:
        sig = site_result.key_signals
        specific = []
        if not sig.get("uses_https"):
            specific.insert(0, "Migrate to HTTPS immediately — browsers mark HTTP as 'Not Secure'.")
        if sig.get("title_len", 60) > 60:
            specific.append(f"Shorten page title (currently {sig.get('title_len')} chars) to 50–60 characters.")
        if not sig.get("meta_desc_len"):
            specific.append("Add a meta description (120–160 chars) — it directly affects click-through rate.")
        if sig.get("h1_count", 1) != 1:
            specific.append(f"Fix H1 tags — page has {sig.get('h1_count', 0)}, should have exactly 1.")
        if sig.get("img_no_alt", 0) > 0:
            specific.append(f"Add alt text to {sig['img_no_alt']} image(s) for accessibility and image SEO.")
        if specific:
            onpage_actions = specific + onpage_actions[:max(0, 5 - len(specific))]

    recs.append({
        "title":    "Optimize On-Page Content",
        "priority": "Medium",
        "rationale": (
            "On-page signals (title, meta, headings, content depth) are foundational ranking factors "
            "that compound with every piece of content published."
        ),
        "actions": onpage_actions[:5],
    })

    # ── 5. Optimize Internal Linking ───────────────────────────────────────────
    il_actions = []
    if not lh_df.empty:
        top_lh = lh_df.iloc[0].get("keyword", "")
        il_actions.append(
            f'Add internal links pointing to the **"{top_lh}"** page from relevant existing pages — '
            "it's close to page 1 and more authority will push it over."
        )
    if not tp_df.empty:
        top_page_url = tp_df.iloc[0].get("url", "")
        il_actions.append(
            f"Build a hub-and-spoke structure: link all related content back to your highest-traffic page ({top_page_url})."
        )
    il_actions += [
        "Audit orphan pages (no internal links pointing to them) — they receive no authority from other pages.",
        "Use descriptive anchor text that includes target keywords rather than generic 'click here' or 'read more'.",
        "Add breadcrumb navigation across category and product pages to strengthen site architecture.",
    ]

    recs.append({
        "title":    "Optimize Internal Linking Throughout the Website",
        "priority": "Medium",
        "rationale": (
            "Internal links distribute page authority (PageRank) across the site and help Google "
            "discover and prioritize important pages. Most sites underuse this lever."
        ),
        "actions": il_actions[:5],
    })

    return recs
