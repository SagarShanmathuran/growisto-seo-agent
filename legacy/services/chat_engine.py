"""Rule-based chat engine — answers SEO analysis questions from session data."""

import pandas as pd


def _fmt(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def answer(question: str, ctx: dict) -> str:
    q = question.lower().strip()

    ahrefs      = ctx.get("ahrefs", {})
    roi         = ctx.get("roi", {})
    verdict     = ctx.get("ai_result", {})
    comp_traffic = ctx.get("comp_traffic", {})
    client_url  = ctx.get("client_url", "the client")
    niche       = ctx.get("niche", "")
    sym         = ctx.get("currency_symbol", "$")
    gaps_df     = ahrefs.get("keyword_gaps", pd.DataFrame())
    lh_df       = ahrefs.get("low_hanging_fruit", pd.DataFrame())
    tp_df       = ahrefs.get("top_comp_pages", pd.DataFrame())
    client_trf  = ahrefs.get("client_total_traffic", 0)
    total_comp  = ctx.get("total_traffic", 0)

    # ── verdict / summary ─────────────────────────────────────────────────────
    if any(w in q for w in ["verdict", "potential", "score", "rating", "result", "summary", "overall"]):
        p = verdict.get("potential", "N/A")
        s = verdict.get("summary", "")
        return f"**SEO Potential: {p}**\n\n{s}"

    # ── ROI ───────────────────────────────────────────────────────────────────
    if any(w in q for w in ["roi", "return", "revenue", "money", "worth", "investment", "profitable"]):
        if not roi:
            return "No ROI data yet — run the analysis in Tab 4 first."
        lines = [
            f"**ROI Estimate for {client_url}:**",
            f"- Competitor total traffic: {_fmt(total_comp)}/mo",
            f"- Achievable traffic (10% capture): {_fmt(roi.get('achievable_traffic',0))}/mo",
            f"- Est. monthly revenue: {sym}{roi.get('monthly_revenue',0):,.0f}",
            f"- Annual ROI: {roi.get('roi_pct',0)}%",
            f"- Viable: {'✅ Yes' if roi.get('is_viable') else '❌ No'}",
        ]
        return "\n".join(lines)

    # ── competitor traffic ─────────────────────────────────────────────────────
    if any(w in q for w in ["competitor", "competition", "traffic", "benchmark", "vs", "compare"]):
        if not comp_traffic:
            return "No competitor data loaded yet."
        sorted_comps = sorted(comp_traffic.items(), key=lambda x: -x[1])
        lines = [f"**Competitor Traffic Benchmark:**",
                 f"- ⭐ {client_url}: {_fmt(client_trf)}/mo"]
        for d, t in sorted_comps:
            gap = t - client_trf
            lines.append(f"- {d}: {_fmt(t)}/mo  (gap: +{_fmt(gap)})" if gap > 0 else f"- {d}: {_fmt(t)}/mo")
        top = sorted_comps[0] if sorted_comps else None
        if top:
            lines.append(f"\n**Strongest competitor:** {top[0]} at {_fmt(top[1])}/mo")
        return "\n".join(lines)

    # ── keyword gaps ──────────────────────────────────────────────────────────
    if any(w in q for w in ["gap", "keyword", "missing", "rank", "ranking", "opportunity", "opportunit"]):
        if gaps_df.empty and lh_df.empty:
            return ("No keyword gap data found. Upload competitor **Organic Keywords CSVs** "
                    "(not Top Pages) in Tab 3 to enable this analysis.")
        lines = []
        if not gaps_df.empty:
            lines.append(f"**{len(gaps_df)} keyword gaps found** (competitors rank top 20, you don't):\n")
            for _, row in gaps_df.head(8).iterrows():
                lines.append(
                    f"- **{row.get('keyword','')}** — vol: {_fmt(row.get('search_volume',0))} | "
                    f"comp pos: #{row.get('competitor_position','?')} | "
                    f"your pos: {row.get('client_position','Not ranking')}"
                )
        if not lh_df.empty:
            lines.append(f"\n**{len(lh_df)} low-hanging fruit** (you rank 11–30, push to top 10):\n")
            for _, row in lh_df.head(5).iterrows():
                lines.append(
                    f"- **{row.get('keyword','')}** — pos: {row.get('current_position','?')} | "
                    f"vol: {_fmt(row.get('search_volume',0))}"
                )
        return "\n".join(lines)

    # ── top pages ─────────────────────────────────────────────────────────────
    if any(w in q for w in ["page", "content", "article", "blog", "url", "replicate", "copy"]):
        if tp_df.empty:
            return "No top competitor pages data. Upload competitor Top Pages CSVs in Tab 3."
        lines = ["**Top competitor pages to replicate:**\n"]
        for _, row in tp_df.head(8).iterrows():
            lines.append(
                f"- [{row.get('url','')}]({row.get('url','')})  \n"
                f"  {row.get('competitor','')} | {_fmt(row.get('traffic',0))}/mo | "
                f"kw: {row.get('top_keyword','')}"
            )
        return "\n".join(lines)

    # ── what to do / next steps ───────────────────────────────────────────────
    if any(w in q for w in ["do", "next", "start", "focus", "recommend", "action", "priority", "plan", "strategy", "first"]):
        steps = []
        p = verdict.get("potential", "")

        if p == "HIGH":
            steps.append("✅ **This prospect is HIGH potential — prioritise outreach.**")
        elif p == "MEDIUM":
            steps.append("⚡ **Medium potential — worth a closer look before committing.**")
        else:
            steps.append("❄️ **Low potential — consider skipping or a very targeted approach.**")

        if not lh_df.empty:
            top_lh = lh_df.iloc[0]
            steps.append(f"1. **Quick win:** Target \"{top_lh.get('keyword','')}\" "
                         f"(currently pos {top_lh.get('current_position','?')}, vol {_fmt(top_lh.get('search_volume',0))}) — "
                         f"small push to top 10 drives immediate traffic.")

        if not gaps_df.empty:
            top_gap = gaps_df.iloc[0]
            steps.append(f"2. **Content gap:** Create content for \"{top_gap.get('keyword','')}\" "
                         f"(vol {_fmt(top_gap.get('search_volume',0))}) — competitor ranks #{top_gap.get('competitor_position','?')}, you don't rank at all.")

        if not tp_df.empty:
            top_pg = tp_df.iloc[0]
            steps.append(f"3. **Replicate:** {top_pg.get('competitor','')} gets "
                         f"{_fmt(top_pg.get('traffic',0))}/mo from [{top_pg.get('url','')}]({top_pg.get('url','')}) — "
                         f"build a competing page targeting \"{top_pg.get('top_keyword','')}\".")

        if roi.get("is_viable"):
            steps.append(f"4. **ROI case:** At {sym}{roi.get('monthly_revenue',0):,.0f}/mo estimated revenue, "
                         f"SEO investment pays back at {roi.get('roi_pct',0)}% annually.")

        return "\n\n".join(steps) if steps else "Run the analysis in Tab 4 first to get recommendations."

    # ── client info ───────────────────────────────────────────────────────────
    if any(w in q for w in ["client", "who", "niche", "industry", "website", "site"]):
        return (f"**Client:** {client_url}\n"
                f"**Niche:** {niche}\n"
                f"**Organic traffic:** {_fmt(client_trf)}/mo\n"
                f"**Keywords tracked:** {_fmt(ahrefs.get('client_total_keywords', 0))}")

    # ── fallback ──────────────────────────────────────────────────────────────
    return (
        "I can answer questions about:\n"
        "- **Verdict / Summary** — *'what's the verdict?'*\n"
        "- **Competitors** — *'compare traffic'*, *'who is the strongest competitor?'*\n"
        "- **Keyword gaps** — *'what keywords are we missing?'*\n"
        "- **Low-hanging fruit** — *'quick wins'*\n"
        "- **Top pages** — *'what pages should we replicate?'*\n"
        "- **ROI** — *'is this worth investing in?'*\n"
        "- **Next steps** — *'what should we do first?'*"
    )
