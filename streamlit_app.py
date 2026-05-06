"""
Streamlit UI for the SEO Potential Analysis Agent.

Two-stage workflow:
  Stage 1 — Triage: URL in → business model, AOV, page count, competitor suggestions
  Stage 2 — Full analysis: drop CSVs → DOCX report

Run: streamlit run streamlit_app.py
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from agent.modules.ahrefs_csv_loader     import load as load_site
from agent.modules.gap_analyzer          import analyze as analyze_gap
from agent.modules.report_data_builder   import build_ahrefs_dict, build_comp_traffic_dict
from agent.modules.business_model_detector import detect as detect_model
from agent.modules.aov_extractor         import extract_aov
from agent.modules.competitor_finder     import find_competitors
from agent.modules.triage_filter         import triage
from agent.services.roi_calculator       import calculate_roi, calculate_roi_scenarios
from agent.services.gemini_client        import synthesize_verdict
from agent.services.word_report          import generate_word_report
from agent.services.short_report         import generate_short_report
from agent.modules.page_content_audit    import audit as page_content_audit
from agent.services.ahrefs_client        import (
    is_configured as ahrefs_is_configured,
    workspace_usage, local_usage_summary,
)
from agent.modules.feedback_log          import (
    record as record_feedback, all_entries as feedback_entries, summary as feedback_summary,
)
from agent.seo_core.analyzer             import SEOAnalyzer


st.set_page_config(
    page_title="Growisto SEO Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Password gate (only fires when APP_PASSWORD is configured) ───────────────
def _gate() -> None:
    """Block app rendering until user supplies the correct password.
    No-op when APP_PASSWORD isn't set (local dev)."""
    expected = ""
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except (FileNotFoundError, Exception):
        expected = ""
    if not expected:
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.strip().startswith("APP_PASSWORD="):
                    expected = line.split("=", 1)[1].strip()
                    break
    if not expected:
        return  # No password configured → open access (local dev)

    if st.session_state.get("auth_ok"):
        return

    st.markdown("### 🔒 Growisto SEO Agent")
    st.caption("Internal tool — sign in to continue.")
    pw = st.text_input("Password", type="password", key="auth_pw_input")
    if st.button("Sign in", type="primary"):
        if pw == expected:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


_gate()

# ── Custom CSS: AI agent theme (Growisto teal + dark accents) ─────────────────
st.markdown("""
<style>
  /* Brand palette */
  :root {
    --brand: #367588;
    --brand-dark: #1D3F4A;
    --brand-light: #E8F4F7;
    --accent: #00D4AA;
    --bg-soft: #F8FAFC;
    --text-primary: #0F172A;
    --text-secondary: #64748B;
  }

  /* Hide Streamlit default header decoration */
  [data-testid="stHeader"] { background: transparent; }

  /* Hero header */
  .agent-hero {
    background: linear-gradient(135deg, #1D3F4A 0%, #367588 100%);
    color: white;
    padding: 2rem 2.5rem;
    border-radius: 16px;
    margin-bottom: 1.5rem;
    box-shadow: 0 10px 40px -10px rgba(54, 117, 136, 0.3);
  }
  .agent-hero h1 {
    margin: 0;
    font-size: 2.2rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .agent-hero p {
    margin: 0.5rem 0 0;
    opacity: 0.85;
    font-size: 1rem;
    font-weight: 400;
  }
  .agent-hero .pill {
    display: inline-block;
    background: rgba(255,255,255,0.15);
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.8rem;
    margin-right: 8px;
    margin-top: 0.8rem;
    backdrop-filter: blur(10px);
  }

  /* Section cards */
  .agent-card {
    background: white;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }

  /* Bigger, friendlier buttons */
  .stButton > button {
    border-radius: 10px;
    font-weight: 600;
    transition: all 0.15s ease;
  }
  .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #367588 0%, #1D3F4A 100%);
    border: none;
    box-shadow: 0 4px 12px -2px rgba(54, 117, 136, 0.4);
  }
  .stButton > button[kind="primary"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 20px -2px rgba(54, 117, 136, 0.5);
  }

  /* Tabs styling */
  .stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background: #F1F5F9;
    padding: 4px;
    border-radius: 10px;
  }
  .stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 500;
  }
  .stTabs [aria-selected="true"] {
    background: white !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }

  /* Metric cards */
  [data-testid="stMetric"] {
    background: white;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 16px 20px;
  }

  /* Sidebar */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #F8FAFC 0%, #FFFFFF 100%);
    border-right: 1px solid #E2E8F0;
  }
  [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    color: var(--brand-dark);
    font-weight: 700;
  }

  /* Status pill */
  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 500;
  }
  .status-pill.green { background: #D1FAE5; color: #065F46; }
  .status-pill.amber { background: #FEF3C7; color: #92400E; }
  .status-pill.red   { background: #FEE2E2; color: #991B1B; }
  .status-pill.blue  { background: #DBEAFE; color: #1E40AF; }
</style>
""", unsafe_allow_html=True)

# Hero
ahrefs_status = "🟢 Ahrefs connected" if ahrefs_is_configured() else "🟡 Ahrefs not configured"
st.markdown(f"""
<div class="agent-hero">
  <h1>🤖 Growisto SEO Agent</h1>
  <p>Auto-discovers competitors via Ahrefs, computes ROI & gap analysis, generates client-ready reports.</p>
  <span class="pill">{ahrefs_status}</span>
  <span class="pill">⚡ Two-stage workflow</span>
  <span class="pill">📊 Incremental-traffic ROI model</span>
</div>
""", unsafe_allow_html=True)


def _save_upload(upload) -> str:
    suffix = Path(upload.name).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(upload.read()); tmp.close()
    return tmp.name


def _derive_name(url_or_domain: str) -> str:
    """kushals.com -> Kushals; vinodcookware.com -> Vinodcookware."""
    s = (url_or_domain or "").replace("https://", "").replace("http://", "")
    s = s.strip("/").replace("www.", "").lower()
    s = s.split("/")[0].split(".")[0]
    return s.replace("-", " ").replace("_", " ").title() or "Client"


# ── Sidebar: shared client inputs ─────────────────────────────────────────────
with st.sidebar:
    st.header("Client")
    client_url  = st.text_input("Client URL", placeholder="vinodcookware.com",
                                 value=st.session_state.get("client_url", ""))
    # Auto-derive from URL if user hasn't typed a name
    _name_default = st.session_state.get("client_name") or (_derive_name(client_url) if client_url else "")
    client_name = st.text_input("Client Name (auto-derived from URL)",
                                 placeholder="auto", value=_name_default)
    if not client_name and client_url:
        client_name = _derive_name(client_url)
    niche       = st.text_input("Niche",    value="General")
    location    = st.text_input("Market",   value="India")

    st.header("ROI Inputs")
    currency  = st.selectbox("Currency", ["₹", "$", "€", "£"], index=0)
    default_aov = st.session_state.get("auto_aov", 2000)
    aov       = st.number_input(f"AOV / Contract Value ({currency})", value=int(default_aov), step=100)
    cvr       = st.number_input("Conversion Rate", value=0.01, step=0.005, format="%.3f",
                                 help="Typical: 1% for ecommerce, 0.5% for high-AOV jewelry, 2-3% for niche subscription")
    seo_cost  = st.number_input(f"Monthly SEO Cost ({currency})", value=150_000, step=10_000)

    skip_crawl = st.checkbox("Skip on-page crawl (faster)", value=False)

    # ── Ahrefs usage panel ────────────────────────────────────────────────────
    st.markdown("---")
    st.header("📊 Ahrefs Usage")
    if ahrefs_is_configured():
        local = local_usage_summary()
        live = workspace_usage()

        if "error" in live:
            st.warning(f"Live usage unavailable: {live['error']}")
        else:
            pct = live["pct_used"]
            bar_color = "🟢" if pct < 60 else ("🟡" if pct < 85 else "🔴")
            st.metric(
                "Workspace usage (live)",
                f"{live['units_used']:,} / {live['units_limit']:,}",
                f"{pct}% used",
            )
            st.progress(min(pct / 100, 1.0))
            st.caption(f"{bar_color} {live['units_remaining']:,} units remaining · resets {live['reset_date'][:10] if live.get('reset_date') else '?'}")

        st.markdown("**This dashboard's consumption:**")
        c1, c2 = st.columns(2)
        c1.metric("Total calls", local["total_calls"])
        c2.metric("Units used",  f"{local['total_units']:,}")
        if local["last_30d_units"] != local["total_units"]:
            st.caption(f"Last 30 days: {local['last_30d_units']:,} units")
        if local["recent"]:
            with st.expander("Recent calls"):
                import pandas as _pd
                rec_df = _pd.DataFrame(local["recent"][::-1])  # newest first
                st.dataframe(rec_df, hide_index=True, use_container_width=True)
    else:
        st.info("Ahrefs not configured. Add `AHREFS_API_TOKEN` to `.env` to enable usage tracking.")


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "🧪  Stage 1 — Triage & Competitors",
    "📊  Stage 2 — Full Analysis",
    "📝  Feedback & Patterns",
])


# ── Stage 1: Competitor Discovery ─────────────────────────────────────────────
with tab1:
    st.subheader("Find SEO Competitors")
    from agent.services.ahrefs_client import is_configured as _ahrefs_ok
    if _ahrefs_ok():
        st.caption("✨ Using **Ahrefs API** — keyword-overlap based competitor discovery (~210 units/call).")
    else:
        st.caption("Using **SerpAPI** seed-based discovery. Add `AHREFS_API_TOKEN` to `.env` for higher-quality competitor matches.")

    manual_seeds_raw = st.text_area(
        "Seed keywords (optional — only used if Ahrefs unavailable)",
        placeholder="diamond ring, diamond earrings, platinum jewellery, diamond necklace",
        help="Used only as a fallback when AHREFS_API_TOKEN is not set. Ahrefs uses keyword-overlap, no seeds needed.",
    )

    if st.button("🔎 Find Competitors", disabled=not client_url):
        manual_seeds = [s.strip() for s in manual_seeds_raw.split(",") if s.strip()] or None
        with st.spinner("Discovering competitors..."):
            comp_result = find_competitors(
                client_url,
                seed_keywords=manual_seeds,
                location=location,
                top_n=10,
            )
        st.session_state["comp_result"] = comp_result
        st.session_state["dismissed_comps"] = set()
        st.session_state["custom_comps"]    = []
        # Clear stale reasoner cache so the next render runs the reasoner fresh
        for k in list(st.session_state.keys()):
            if isinstance(k, str) and k.startswith("reasoner_"):
                del st.session_state[k]

    # Render competitors if we have a cached result (so adds/dismisses persist)
    comp_result = st.session_state.get("comp_result")
    if comp_result:

        source = comp_result.get("source", "unknown")
        if source in ("ahrefs", "ahrefs+llm"):
            cost = comp_result.get("units_cost", 0)
            llm_added = comp_result.get("llm_peers_added", 0)
            cat = comp_result.get("category_understood", "")
            llm_status = comp_result.get("llm_status", "skipped")
            skipped_reason = comp_result.get("llm_skip_reason", "")
            llm_suggestions = comp_result.get("llm_all_suggestions", [])

            extras = []
            if llm_added:
                extras.append(f"+ {llm_added} new brand peers via LLM")
            extra_str = "  ·  " + "  ·  ".join(extras) if extras else ""
            st.success(f"✅ {len(comp_result['competitors'])} candidates  ·  Cost: {cost} units{extra_str}")

            # ── LLM positioning verification (the "how do I trust this?" answer) ──
            if llm_status == "gemini" and cat:
                st.info(f"🧠 **Gemini understood the category as:** _{cat}_")

                # Show the LLM's actual peer suggestions so analyst can compare
                if llm_suggestions:
                    ahrefs_doms = {c["domain"].lower() for c in comp_result["competitors"]}
                    overlap = [s for s in llm_suggestions if s.get("domain","").lower() in ahrefs_doms]
                    new_brands = [s for s in llm_suggestions if s.get("domain","").lower() not in ahrefs_doms]

                    with st.expander(f"🔍 Gemini's {len(llm_suggestions)} peer brand suggestions  ·  "
                                      f"{len(overlap)} match Ahrefs picks  ·  {len(new_brands)} new", expanded=True):
                        if overlap:
                            st.markdown("**✓ Gemini agrees with these Ahrefs picks** (high confidence):")
                            for s in overlap:
                                st.markdown(f"- **{s.get('domain')}** — _{s.get('rationale','')}_")
                        if new_brands:
                            st.markdown("**➕ Gemini suggested these (not in Ahrefs results)**:")
                            for s in new_brands:
                                in_added = s.get("domain","").lower() in {c["domain"].lower() for c in comp_result["competitors"] if c.get("source") == "llm"}
                                badge = " ✓ added & validated" if in_added else " (not validated — Ahrefs has no metrics for this domain in target country)"
                                st.markdown(f"- **{s.get('domain')}**{badge} — _{s.get('rationale','')}_")
                        if not overlap and not new_brands:
                            st.markdown("_No suggestions returned._")
            elif llm_status == "skipped":
                # Try to figure out *why* it skipped so we can give actionable advice
                from agent.services.config import get_secret as _gs
                _gem_key = _gs("GEMINI_API_KEY")
                if not _gem_key:
                    st.error(
                        "❌ **Gemini's positioning check did not run — `GEMINI_API_KEY` is not configured.**  \n\n"
                        "**Fix:** open https://share.streamlit.io → your app → ⋮ → Settings → Secrets, "
                        "and add a line like:  \n"
                        "`GEMINI_API_KEY = \"AIza...\"`  \n\n"
                        "Get a key at https://aistudio.google.com/apikey (free tier — no billing needed)."
                    )
                else:
                    st.warning(
                        f"⚠ **Gemini's positioning check did not run.** {skipped_reason or 'Reason unknown.'}  \n\n"
                        f"Possible causes: rate-limit (429), Gemini overload (503), invalid key (401), "
                        f"or the project has zero free-tier quota allocated.  \n"
                        f"Without it, picks are based on **Ahrefs keyword overlap + traffic ratio only**, "
                        f"which can mis-fit positioning. **Manually verify each pick.**"
                    )
        elif source == "serpapi" and comp_result.get("seed_keywords"):
            st.info(f"SerpAPI · seeds: {', '.join(comp_result['seed_keywords'][:6])}")

        for e in comp_result.get("errors", []):
            st.warning(e)

        # Live, mutable competitor list (analyst can dismiss / add custom)
        dismissed = st.session_state.get("dismissed_comps", set())
        custom_comps = st.session_state.get("custom_comps", [])
        active_comps = [c for c in comp_result["competitors"] if c["domain"] not in dismissed]

        # ── Run the reasoner ONCE per result and cache in session state ──────
        reasoner_key = f"reasoner_{client_url}"
        if reasoner_key not in st.session_state and active_comps:
            from agent.modules.competitor_reasoner import reason as run_reasoner
            from agent.modules.business_model_detector import detect as detect_bm
            from agent.modules.seed_extractor import extract_seeds_from_sitemap

            client_row_data = comp_result.get("client_row") or {}
            with st.spinner("🧠 Agent reasoning — applying SEO analyst rules..."):
                # Cheap: detect business model + niche hint from sitemap seeds
                bm = detect_bm(client_url)
                seeds = extract_seeds_from_sitemap(client_url, top_n=5)
                niche_hint = ", ".join(seeds) if seeds else (niche if niche != "General" else "")

                rr = run_reasoner(
                    client_url=client_url,
                    client_name=client_name,
                    business_model=bm.primary,
                    client_traffic=int(client_row_data.get("traffic", 0)),
                    client_keywords_total=int(client_row_data.get("keywords_total", 0)),
                    client_dr=0,   # not in Ahrefs metrics endpoint
                    niche_hint=niche_hint,
                    candidates=[
                        {
                            "domain":          c["domain"],
                            "type":            c.get("type", "unknown"),
                            "keywords_common": c.get("keywords_common", 0),
                            "traffic":         c.get("traffic", 0),
                            "domain_rating":   c.get("domain_rating", 0),
                        }
                        for c in active_comps
                    ],
                    location=location,
                )
            st.session_state[reasoner_key] = rr
        rr = st.session_state.get(reasoner_key)

        if active_comps or custom_comps:
            client_row = comp_result.get("client_row")

            # ── Headline gap stat ─────────────────────────────────────────
            if client_row and client_row.get("traffic", 0) > 0:
                client_trf = client_row["traffic"]
                gaps = [c["traffic"] / client_trf for c in active_comps if c.get("traffic", 0) > 0]
                if gaps:
                    avg_gap = sum(gaps) / len(gaps)
                    top_gap = max(gaps)
                    st.caption(
                        f"📈 **Traffic gap:** competitors are on average **{avg_gap:.1f}× larger** "
                        f"(top: **{top_gap:.1f}×**) than the client."
                    )

            # ── Client row ────────────────────────────────────────────────
            if client_row:
                col_a, col_b, col_c, col_d, col_e = st.columns([2.5, 1.2, 1.2, 1, 1.5])
                col_a.markdown(f"**★ CLIENT — {client_row['domain']}**")
                col_b.markdown("—")
                col_c.markdown(f"{client_row.get('keywords_total', 0):,} kws")
                col_d.markdown("—")
                col_e.markdown(f"{client_row.get('traffic', 0):,} traffic")
                st.markdown("---")

            # ── Competitor rows with Use / Dismiss buttons ────────────────
            selected_comps = st.session_state.setdefault("selected_comps", [])
            selected_domains = {c["domain"] for c in selected_comps}

            # ── Type filter toggle ────────────────────────────────────────
            from agent.modules.competitor_classifier import TYPE_BADGE, TYPE_PRIORITY
            filter_col1, filter_col2 = st.columns([1.5, 5])
            type_filter = filter_col1.selectbox(
                "Filter by type",
                ["All", "🏢 Brands only", "🏢 + ❓ (no retailers)"],
                key="type_filter",
                label_visibility="collapsed",
            )

            # Apply filter
            if type_filter == "🏢 Brands only":
                active_comps = [c for c in active_comps if c.get("type") == "brand"]
            elif type_filter == "🏢 + ❓ (no retailers)":
                active_comps = [c for c in active_comps if c.get("type") in ("brand", "unknown")]

            # Sort: tier 1 first, then tier 2, then off-target. Within tiers,
            # brands first, then by keyword overlap.
            def _tier_rank(d: str) -> int:
                if rr and d in {x["domain"] for x in rr.get("tier_1", [])}: return 0
                if rr and d in {x["domain"] for x in rr.get("tier_2", [])}: return 1
                if rr and d in {x["domain"] for x in rr.get("off_target", [])}: return 2
                return 1
            active_comps = sorted(active_comps, key=lambda c: (
                _tier_rank(c["domain"]),
                TYPE_PRIORITY.get(c.get("type", "unknown"), 5),
                -c.get("keywords_common", 0),
            ))

            # Type-distribution summary
            from collections import Counter
            type_dist = Counter(c.get("type", "unknown") for c in comp_result["competitors"])
            dist_str = "  ·  ".join(
                f"{TYPE_BADGE.get(t, t)}: {n}" for t, n in type_dist.most_common()
            )
            filter_col2.caption(f"Distribution: {dist_str}")

            # ── Agent's top 3 picks (the headline) ───────────────────────
            if rr:
                src_label = "Gemini Flash" if rr.get("source") == "gemini" else "deterministic heuristic"
                top_3_picks = rr.get("top_3_picks", [])
                alternates  = rr.get("alternates", [])
                offtgt_set  = {x["domain"] for x in rr.get("off_target", [])}
                reason_lookup = {
                    x["domain"]: x.get("reason", "")
                    for key in ["top_3_picks", "alternates", "off_target"]
                    for x in rr.get(key, [])
                }
                conf_lookup = {x["domain"]: x.get("confidence", "medium") for x in top_3_picks}
                top_3_domains = {x["domain"] for x in top_3_picks}

                st.markdown(f"### 🎯 Agent's Top 3 Picks  _(via {src_label})_")
                if rr.get("summary"):
                    st.caption(rr["summary"])
                if rr.get("warning"):
                    st.warning(rr["warning"])

                # ── 🔍 SERP cross-check (third confidence layer, opt-in) ─────
                serp_key = f"serp_validate_{client_url}"
                serp_data = st.session_state.get(serp_key)
                if not serp_data:
                    sc1, sc2 = st.columns([1, 4])
                    if sc1.button("🔍 Cross-check via SERP",
                                  help="Run SerpAPI on Gemini-suggested transactional keywords (~₹3-5 cost) "
                                       "to see which brands actually rank in Google today."):
                        from agent.modules.serp_validator import validate_via_serp
                        from agent.modules.business_model_detector import detect as _detect_bm
                        from agent.modules.seed_extractor import extract_seeds_from_sitemap
                        with st.spinner("Asking Gemini for transactional kws + running 5–7 SERPs..."):
                            _bm = _detect_bm(client_url)
                            _seeds = extract_seeds_from_sitemap(client_url, top_n=5)
                            _niche = ", ".join(_seeds) if _seeds else (niche if niche != "General" else "")
                            serp_data = validate_via_serp(
                                client_url=client_url, client_name=client_name,
                                business_model=_bm.primary, niche_hint=_niche,
                                location=location, max_keywords=6,
                            )
                            st.session_state[serp_key] = serp_data
                            st.rerun()
                    sc2.caption("_The third confidence layer — confirms which brands actually rank for "
                                "high-intent buyer keywords in Google today._")

                if serp_data:
                    cost = serp_data.get("cost_estimate", 0)
                    n_kws = len(serp_data.get("keywords", []))
                    n_brands = len(serp_data.get("ranking_brands", {}))
                    st.success(f"✅ SERP check ran on {n_kws} transactional keywords  ·  "
                               f"Found {n_brands} ranking brands  ·  Estimated cost: ₹{cost:.2f}")
                    with st.expander(f"🔍 SERP validation details  ·  {n_kws} keywords checked", expanded=False):
                        st.markdown("**Transactional keywords checked:**")
                        for k in serp_data.get("keywords", []):
                            st.markdown(f"- {k}")
                        if serp_data.get("ranking_brands"):
                            st.markdown("\n**Top ranking brands across these SERPs:**")
                            import pandas as _pd
                            rb_rows = []
                            for d, info in list(serp_data["ranking_brands"].items())[:15]:
                                rb_rows.append({
                                    "Domain":           d,
                                    "Frequency":        info["frequency"],
                                    "Avg Position":     info["avg_position"],
                                    "Best Position":    info["best_position"],
                                    "Ranks for":        ", ".join(info["in_kws"][:3]),
                                })
                            st.dataframe(_pd.DataFrame(rb_rows), hide_index=True, use_container_width=True)
                        if serp_data.get("errors"):
                            for e in serp_data["errors"]:
                                st.warning(e)

                # Build LLM agreement set — picks that Gemini also suggested
                llm_agree_doms = {
                    s.get("domain", "").lower()
                    for s in comp_result.get("llm_all_suggestions", [])
                }
                llm_ran = comp_result.get("llm_status") == "gemini"

                # SERP confirmation set — picks that ranked in actual SERPs
                serp_confirmed = {
                    d.lower() for d in (serp_data or {}).get("ranking_brands", {}).keys()
                }
                serp_ran = bool(serp_data)

                # Big cards for the top 3
                comp_lookup = {c["domain"]: c for c in active_comps}
                conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}
                for pick in top_3_picks:
                    d = pick["domain"]
                    c = comp_lookup.get(d, {"type": "unknown", "keywords_common": 0,
                                              "domain_rating": 0, "traffic": 0})
                    conf = pick.get("confidence", "medium")
                    already_selected = d in selected_domains

                    # Positioning-fit badge: did Gemini also suggest this domain?
                    if llm_ran:
                        if d.lower() in llm_agree_doms:
                            fit_badge = "✓ Gemini agrees"
                            fit_color = "green"
                        else:
                            fit_badge = "⚠ Not in Gemini's peer list"
                            fit_color = "orange"
                    else:
                        fit_badge = "❓ Gemini didn't run"
                        fit_color = "grey"

                    # SERP-confirmed badge (third layer, opt-in)
                    if serp_ran:
                        if d.lower() in serp_confirmed:
                            serp_badge = "✓ Ranks in SERP"
                            serp_color = "green"
                        else:
                            serp_badge = "⚠ Doesn't rank in SERP for transactional kws"
                            serp_color = "orange"
                    else:
                        serp_badge = ""
                        serp_color = ""

                    with st.container(border=True):
                        cols = st.columns([2.5, 1.0, 1.5, 0.8, 1.2, 1.0])
                        cols[0].markdown(f"### {conf_emoji.get(conf, '🟡')} **{d}**")
                        cols[0].markdown(f"<span style='color:{fit_color};font-size:0.85em;font-weight:600'>{fit_badge}</span>", unsafe_allow_html=True)
                        if serp_badge:
                            cols[0].markdown(f"<span style='color:{serp_color};font-size:0.85em;font-weight:600'>{serp_badge}</span>", unsafe_allow_html=True)
                        cols[1].markdown(f"{TYPE_BADGE.get(c.get('type', 'unknown'), '?')}")
                        cols[2].markdown(f"**{c.get('traffic', 0):,}** traffic")
                        cols[3].markdown(f"DR **{c.get('domain_rating', 0):.0f}**")
                        cols[4].markdown(f"**{c.get('keywords_common', 0):,}** kw common")
                        if already_selected:
                            cols[5].success("✅ Selected")
                        else:
                            if cols[5].button("✓ Use", key=f"toppick_{d}", type="primary",
                                              help="Send to Stage 2", use_container_width=True):
                                selected_comps.append({
                                    "domain": d, "name": _derive_name(d),
                                    "traffic": c.get("traffic", 0),
                                })
                                st.session_state["selected_comps"] = selected_comps
                                st.toast(f"Added {d} to Stage 2", icon="✅")
                                st.rerun()
                        st.markdown(f"💡 _{pick.get('reason', '')}_")
            else:
                top_3_domains, alternates, offtgt_set, reason_lookup = set(), [], set(), {}

            # ── Alternates / Off-target (collapsible) ────────────────────
            tier_badge = {0: "✅ Top 3", 1: "⚠️ Alt", 2: "❌ Off"}

            def _tier_rank_v2(d: str) -> int:
                if d in top_3_domains: return 0
                if rr and d in {x["domain"] for x in rr.get("off_target", [])}: return 2
                return 1

            non_top3 = [c for c in active_comps if c["domain"] not in top_3_domains]
            if non_top3:
                with st.expander(f"View {len(non_top3)} alternates / off-target candidates", expanded=False):
                    for c in non_top3:
                        col_tr, col_a, col_t, col_d, col_e, col_use, col_dis = st.columns([0.7, 2.0, 1.0, 0.7, 1.2, 0.7, 0.5])
                        tier = _tier_rank_v2(c["domain"])
                        col_tr.markdown(f"**{tier_badge[tier]}**")
                        col_a.markdown(f"**{c['domain']}**")
                        col_t.markdown(f"{TYPE_BADGE.get(c.get('type', 'unknown'), '?')}")
                        col_d.markdown(f"DR {c.get('domain_rating', 0):.0f}")
                        col_e.markdown(f"{c.get('traffic', 0):,}")

                        already_selected = c["domain"] in selected_domains
                        if already_selected:
                            col_use.markdown("✅")
                        else:
                            if col_use.button("✓", key=f"use_{c['domain']}", help="Send to Stage 2"):
                                selected_comps.append({
                                    "domain": c["domain"],
                                    "name":   _derive_name(c["domain"]),
                                    "traffic": c.get("traffic", 0),
                                })
                                st.session_state["selected_comps"] = selected_comps
                                st.rerun()
                        if col_dis.button("✕", key=f"dismiss_{c['domain']}", help="Dismiss"):
                            dismissed.add(c["domain"])
                            st.session_state["dismissed_comps"] = dismissed
                            record_feedback(
                                kind="competitor_dismissed",
                                client_url=client_url, client_name=client_name, niche=niche,
                                payload={"domain": c["domain"], "source": source},
                            )
                            st.rerun()
                        reason_text = reason_lookup.get(c["domain"], "")
                        if reason_text:
                            st.caption(f"   ↳ _{reason_text}_")

            # ── Stage 2 selection summary ─────────────────────────────────
            if selected_comps:
                st.markdown("---")
                st.success(
                    f"**🎯 {len(selected_comps)} competitor(s) selected for Stage 2:** "
                    + ", ".join(c["domain"] for c in selected_comps)
                    + "  ·  Switch to Stage 2 tab to upload their CSVs."
                )
                if st.button("Clear selection", key="clear_selected"):
                    st.session_state["selected_comps"] = []
                    st.rerun()

            # ── Manually-added custom competitors ─────────────────────────
            if custom_comps:
                st.markdown("**➕ Custom competitors (analyst-added)**")
                for d in custom_comps:
                    col_a, col_f = st.columns([5, 0.8])
                    col_a.markdown(f"**{d}**  _(manual)_")
                    if col_f.button("✕", key=f"rm_custom_{d}"):
                        custom_comps.remove(d)
                        st.session_state["custom_comps"] = custom_comps
                        st.rerun()

            # ── Add a custom competitor ───────────────────────────────────
            with st.expander("➕ Add competitor manually"):
                new_dom = st.text_input("Competitor domain", placeholder="competitor.com",
                                         key="new_comp_input", label_visibility="collapsed")
                add_col, _ = st.columns([1, 4])
                if add_col.button("Add", type="primary", key="add_comp_btn"):
                    if new_dom and new_dom not in custom_comps:
                        clean = new_dom.replace("https://", "").replace("http://", "").strip("/").replace("www.", "").lower()
                        custom_comps.append(clean)
                        st.session_state["custom_comps"] = custom_comps
                        record_feedback(
                            kind="competitor_added",
                            client_url=client_url,
                            client_name=client_name,
                            niche=niche,
                            payload={"domain": clean, "reason": "analyst_manual"},
                        )
                        st.rerun()

            # ── Overall feedback on Ahrefs suggestions ────────────────────
            st.markdown("---")
            st.markdown("**💬 How were the suggestions?**")
            fb_col1, fb_col2, fb_col3 = st.columns([1, 1, 4])
            if fb_col1.button("👍 Helpful", key="fb_helpful"):
                record_feedback(
                    kind="competitor_rating",
                    client_url=client_url, client_name=client_name, niche=niche,
                    payload={"helpful": True, "source": source,
                             "kept_count": len(active_comps),
                             "dismissed_count": len(dismissed),
                             "added_count": len(custom_comps)},
                )
                st.toast("Thanks — feedback saved", icon="✅")
            if fb_col2.button("👎 Off-target", key="fb_unhelpful"):
                record_feedback(
                    kind="competitor_rating",
                    client_url=client_url, client_name=client_name, niche=niche,
                    payload={"helpful": False, "source": source,
                             "kept_count": len(active_comps),
                             "dismissed_count": len(dismissed),
                             "added_count": len(custom_comps)},
                )
                st.toast("Logged — we'll learn from this", icon="📝")

            note = fb_col3.text_input("Note (optional)", placeholder="What use-case did Ahrefs miss?",
                                       key="fb_note", label_visibility="collapsed")
            if note and st.button("Save note", key="save_note_btn"):
                record_feedback(
                    kind="analysis_note",
                    client_url=client_url, client_name=client_name, niche=niche,
                    payload={"note": note},
                )
                st.toast("Note saved", icon="✅")

            st.info("👉 Pick the relevant competitors above → export their Ahrefs CSVs → upload in Stage 2")
        elif not comp_result.get("errors"):
            st.info("No clear competitors returned. Add custom ones below.")


# ── Stage 2: Full analysis ────────────────────────────────────────────────────
with tab2:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📄 Client Ahrefs Keywords CSV")
        st.caption("Just one file — page-level data is auto-derived from the keywords export.")
        client_kw = st.file_uploader("Client — Organic Keywords CSV", type=["csv"], key="ckw")

    with col2:
        st.subheader("🏢 Competitors")
        selected_comps = st.session_state.get("selected_comps", [])

        if not selected_comps:
            st.info("👈 Pick competitors in **Stage 1** first (click ✓ Use). Or add a manual one below.")
            with st.expander("➕ Add a competitor manually"):
                manual_dom = st.text_input("Competitor domain", placeholder="kushals.com",
                                            key="manual_comp_stage2")
                if st.button("Add", key="add_manual_stage2"):
                    if manual_dom:
                        clean = manual_dom.replace("https://", "").replace("http://", "").strip("/").replace("www.", "").lower()
                        st.session_state.setdefault("selected_comps", []).append({
                            "domain": clean, "name": _derive_name(clean), "traffic": 0,
                        })
                        st.rerun()

        competitors_input = []
        for i, comp in enumerate(selected_comps):
            with st.expander(f"📁 {comp['name']} ({comp['domain']})", expanded=(i == 0)):
                ck = st.file_uploader(f"Keywords CSV — {comp['domain']}",
                                       type=["csv"], key=f"ck{i}_{comp['domain']}")
                col_a, col_b = st.columns([4, 1])
                if col_b.button("Remove", key=f"rm_{comp['domain']}"):
                    st.session_state["selected_comps"] = [
                        c for c in selected_comps if c["domain"] != comp["domain"]
                    ]
                    st.rerun()
                competitors_input.append((comp["name"], ck))

    st.markdown("---")
    ready = bool(client_url) and bool(client_name) and bool(client_kw) and \
            len(competitors_input) > 0 and \
            any(ck for _, ck in competitors_input)

    if not ready:
        missing = []
        if not client_url:  missing.append("Client URL")
        if not client_name: missing.append("Client Name")
        if not client_kw:   missing.append("Client keywords CSV")
        if not competitors_input: missing.append("at least 1 competitor (use Stage 1 ✓ Use)")
        elif not any(ck for _, ck in competitors_input):
            missing.append("Keywords CSV for at least 1 competitor")
        if missing:
            st.warning(f"**Missing to enable Generate:** {' · '.join(missing)}")

    if st.button("🚀 Generate Report", type="primary", disabled=not ready):
        progress = st.progress(0, text="Loading client CSV...")

        client = load_site(client_name, _save_upload(client_kw))
        progress.progress(15, text="Loading competitor CSVs...")

        competitors = []
        for cn, ck in competitors_input:
            if cn and ck:
                competitors.append(load_site(cn, _save_upload(ck)))

        progress.progress(30, text="Detecting business model...")
        bm = detect_model(client_url)

        site_result = None
        if not skip_crawl:
            progress.progress(45, text="Crawling client site...")
            try:
                site_result = SEOAnalyzer().analyze(client_url)
            except Exception as e:
                st.warning(f"On-page crawl failed: {e}")

        progress.progress(60, text="Computing gap analysis (LLM relevance filter)...")
        # Pass client_url + niche so the LLM relevance filter has scope context
        from agent.modules.seed_extractor import extract_seeds_from_sitemap as _sx
        _seeds = _sx(client_url, top_n=5) if client_url else []
        _niche_hint = ", ".join(_seeds) if _seeds else (niche if niche != "General" else "")
        gap = analyze_gap(client, competitors,
                          business_model=bm.primary,
                          client_url=client_url,
                          niche_hint=_niche_hint)

        progress.progress(75, text="Computing ROI...")
        avg_comp_traffic = int(sum(c.nb_traffic for c in competitors) / len(competitors)) if competitors else 0
        # Incremental-traffic ROI: target = avg competitor traffic (realistic 6-12 month goal)
        roi = calculate_roi(
            client_current_traffic=client.nb_traffic,
            target_traffic=avg_comp_traffic,
            aov=aov, conversion_rate=cvr, monthly_seo_cost=seo_cost,
        )
        roi_scenarios = calculate_roi_scenarios(
            client.nb_traffic, [c.nb_traffic for c in competitors],
            aov=aov, conversion_rate=cvr, monthly_seo_cost=seo_cost,
        )

        progress.progress(85, text="Synthesizing verdict...")
        verdict_input = {
            "client_name": client_name, "client_url": client_url, "niche": niche,
            "client_traffic": client.nb_traffic, "avg_comp_traffic": avg_comp_traffic,
            "traffic_ratio": gap.traffic_ratio, "gap_total_volume": gap.gap_total_volume,
            "top_gap_keywords": [(g.keyword, g.volume, g.best_competitor, g.competitor_rank)
                                 for g in gap.gap_keywords[:10]],
            "page_count_delta": gap.page_count_delta, "business_model": bm.primary,
            "roi_pct": roi["roi_pct"], "roi_viable": roi["is_viable"], "notes": gap.notes,
        }
        verdict = synthesize_verdict(verdict_input)

        progress.progress(92, text="Generating Word reports...")
        ahrefs_dict = build_ahrefs_dict(client, competitors, gap)
        comp_traffic = build_comp_traffic_dict(competitors)
        docx_bytes = generate_word_report(
            client_url=client_url, niche=niche, location=location, currency_symbol=currency,
            ai_result=verdict, roi=roi, comp_traffic=comp_traffic,
            ahrefs=ahrefs_dict, site_result=site_result,
            roi_scenarios=roi_scenarios,
        )

        # ── Short report — focused 5-section format ─────────────────────────
        progress.progress(96, text="Auditing top page content for short report...")
        page_audit = None
        try:
            # Audit the client's top traffic page (best signal of how categories are built)
            top_page_url = client_url
            if not client.pages.empty:
                top_page_url = str(client.pages.iloc[0]["URL"]) or client_url
            page_audit = page_content_audit(top_page_url)
        except Exception as e:
            st.warning(f"Page content audit failed: {e}")

        short_docx_bytes = generate_short_report(
            client_url=client_url, client_name=client_name, niche=niche, location=location,
            ai_result=verdict, gap=gap, comp_traffic=comp_traffic,
            client_total_traffic=client.nb_traffic,
            keyword_rank_comparison=ahrefs_dict.get("keyword_rank_comparison", pd.DataFrame()),
            page_traffic_comparison=ahrefs_dict.get("page_traffic_comparison", pd.DataFrame()),
            page_audit=page_audit,
            site_result=site_result,
        )
        progress.progress(100); progress.empty()

        color = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(verdict["potential"], "⚪")
        st.success(f"## {color} SEO Potential: **{verdict['potential']}**")
        st.markdown(f"**Verdict:** {verdict['summary']}")

        st.markdown("### 📊 Headline Numbers")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Client Traffic",   f"{client.nb_traffic:,}")
        c2.metric("Avg Comp Traffic", f"{avg_comp_traffic:,}")
        c3.metric("Gap Keywords",     f"{len(gap.gap_keywords)} ({gap.gap_total_volume/1000:.0f}K vol)")
        c4.metric("Page Delta",       f"+{gap.page_count_delta}")

        st.markdown("### 💰 ROI — Incremental Traffic Model")
        st.caption(
            f"Formula: (target − current traffic) × {cvr:.0%} CVR × {currency}{aov:,.0f} AOV. "
            f"Retainer: {currency}{seo_cost:,.0f}/mo. Compares against three target scenarios."
        )
        roi_rows = []
        for label, key in [("Conservative (lowest comp)", "conservative"),
                           ("Realistic (avg comp)",       "realistic"),
                           ("Aggressive (top comp)",      "aggressive")]:
            sc = roi_scenarios[key]
            verdict_emoji = {"strong": "🟢", "marginal": "🟡", "weak": "🔴"}.get(sc["viability"], "⚪")
            roi_rows.append({
                "Scenario":            label,
                "Target Traffic":      f"{sc['target_traffic']:,}",
                "Incremental":         f"+{sc['incremental_traffic']:,}",
                "Orders/mo":           f"{sc['incremental_orders']:,}",
                "Revenue/mo":          f"{currency}{sc['monthly_revenue']:,.0f}",
                "ROI Multiple":        f"{verdict_emoji} {sc['roi_multiple']}x",
                "Verdict":             sc["viability"].upper(),
            })
        st.dataframe(pd.DataFrame(roi_rows), use_container_width=True, hide_index=True)

        # ── Big Win Opportunities (actionable highlights) ────────────────
        if gap.big_wins:
            st.markdown("### 🏆 Top Big-Win Opportunities")
            st.caption("Ranked by competitor's *actual* captured traffic — not theoretical volume. These are the highest-leverage pages to build/optimise first.")
            for i, w in enumerate(gap.big_wins, 1):
                with st.container(border=True):
                    cols = st.columns([0.5, 4.5, 1.2, 1.2])
                    cols[0].markdown(f"### **#{i}**")
                    cols[1].markdown(f"**{w.keyword}**  ·  vol {w.volume:,}/mo")
                    cols[2].metric("Comp captures", f"{w.competitor_traffic:,} /mo")
                    cols[3].metric("Client", w.client_rank)
                    st.markdown(f"💡 _{w.pitch}_")

        st.markdown("### 💡 Key Notes")
        for n in gap.notes:
            st.markdown(f"- {n}")

        st.markdown("### 🎯 Top Gap Keywords")
        gaps_df = pd.DataFrame([
            {"Keyword": g.keyword, "Volume": g.volume, "Best Competitor": g.best_competitor,
             "Comp Rank": g.competitor_rank, "Client Rank": g.client_rank}
            for g in gap.gap_keywords[:15]
        ])
        st.dataframe(gaps_df, use_container_width=True, hide_index=True)

        st.markdown("---")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        full_fname  = f"seo_report_{client_name.replace(' ', '_')}_{ts}.docx"
        short_fname = f"seo_report_short_{client_name.replace(' ', '_')}_{ts}.docx"

        st.markdown("### 📥 Download Reports")
        d1, d2 = st.columns(2)
        d1.download_button(
            "📄 Short Report (5 sections, sales-ready)",
            data=short_docx_bytes, file_name=short_fname,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary", use_container_width=True,
        )
        d2.download_button(
            "📚 Full Report (all sections)",
            data=docx_bytes, file_name=full_fname,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    # (the warning above already explains what's missing when not ready)


# ── Tab 3: Feedback & Patterns ────────────────────────────────────────────────
with tab3:
    st.markdown("### 📝 Feedback & Patterns")
    st.caption("Track what's working and what isn't across the 20-30 sites you're testing. The agent learns from this.")

    s = feedback_summary()
    if s["total"] == 0:
        st.info("No feedback yet. Run a few analyses in Stage 1 and use the 👍/👎 buttons to start tracking.")
    else:
        # Summary cards
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Sites Analyzed",     s["sites_analyzed"])
        c2.metric("Total Feedback",     s["total"])
        c3.metric("Ahrefs 👍 Helpful",   s["ahrefs_helpful"])
        c4.metric("Ahrefs 👎 Off",       s["ahrefs_not_helpful"])
        if s["ahrefs_helpful"] + s["ahrefs_not_helpful"] > 0:
            hit_rate = s["ahrefs_helpful"] / (s["ahrefs_helpful"] + s["ahrefs_not_helpful"]) * 100
            c5.metric("Hit Rate",       f"{hit_rate:.0f}%")
        else:
            c5.metric("Hit Rate",       "—")

        # Most-dismissed competitors (if any patterns)
        from collections import Counter
        dismissed_counter = Counter(s.get("dismissed", []))
        added_counter     = Counter(s.get("manually_added", []))

        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown("**Most-dismissed Ahrefs picks**")
            if dismissed_counter:
                df_d = pd.DataFrame(dismissed_counter.most_common(10), columns=["Domain", "Times Dismissed"])
                st.dataframe(df_d, hide_index=True, use_container_width=True)
            else:
                st.caption("None yet")
        with col_right:
            st.markdown("**Most analyst-added competitors**")
            if added_counter:
                df_a = pd.DataFrame(added_counter.most_common(10), columns=["Domain", "Times Added"])
                st.dataframe(df_a, hide_index=True, use_container_width=True)
            else:
                st.caption("None yet")

        # Recent activity
        st.markdown("---")
        st.markdown("**🕒 Recent activity**")
        entries = feedback_entries()[-30:][::-1]  # last 30, newest first
        rows = []
        for e in entries:
            rows.append({
                "When":    e.get("ts", "")[:16].replace("T", " "),
                "Site":    e.get("client_name") or e.get("client_url", "")[:35],
                "Niche":   e.get("niche", ""),
                "Action":  e.get("kind", ""),
                "Detail":  e.get("domain") or e.get("note") or
                           (f"helpful={e.get('helpful')}" if "helpful" in e else ""),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        # Export feedback log
        st.markdown("---")
        import json as _json
        log_data = _json.dumps(feedback_entries(), indent=2)
        st.download_button(
            "📥 Export feedback log (JSON)",
            data=log_data,
            file_name=f"analyst_feedback_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json",
        )
