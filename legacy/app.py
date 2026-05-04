"""
SEO Potential Analyzer — Streamlit Dashboard
Run: streamlit run app.py
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from src.analyzer import SEOAnalyzer
from services.word_report import generate_word_report
from services.serp_client import fetch_competitors
from services.keyword_suggester import scrape_product_terms, get_real_keywords_from_autocomplete
from services.ahrefs_analyzer import (
    parse_top_pages,
    parse_organic_keywords,
    detect_format,
    estimate_traffic,
    find_keyword_gaps,
    full_analysis,
    _find as _af,
)
from services.roi_calculator import calculate_roi
import services.claude_client as cc

# ── page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SEO Potential Analyzer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Settings")
    serp_key   = st.text_input("SearchAPI Key *", type="password", key="serp_key_input")
    claude_key = st.text_input("Claude API Key", type="password", key="claude_key_input",
                               help="Optional — enables AI-written verdict. Without it, scoring is rule-based.")
    st.divider()
    st.markdown("**How to use:**")
    st.markdown("1️⃣ Set up client info  \n2️⃣ Find competitors via keywords  \n3️⃣ Upload Ahrefs CSVs  \n4️⃣ Run analysis")
    st.divider()
    st.caption("SEO Potential Analyzer v2.0")

# ── header ────────────────────────────────────────────────────────────────────

st.title("🔍 SEO Potential Analyzer")
st.caption("Upload Ahrefs data dumps → analyse SEO potential → download Word report")

tab1, tab2, tab3, tab4 = st.tabs([
    "1️⃣  Client Setup",
    "2️⃣  Find Competitors",
    "3️⃣  Upload Ahrefs Data",
    "4️⃣  Analysis & Report",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Client Setup
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    st.header("Client Website Setup")

    col_a, col_b = st.columns(2)

    _CURRENCY = {
        "United States": ("$", "USD"), "United Kingdom": ("£", "GBP"),
        "India": ("₹", "INR"), "Australia": ("A$", "AUD"),
        "Canada": ("C$", "CAD"), "Germany": ("€", "EUR"),
        "France": ("€", "EUR"), "Singapore": ("S$", "SGD"), "UAE": ("AED", "AED"),
    }
    _AOV_DEFAULTS = {
        "United States": 50.0, "United Kingdom": 40.0, "India": 2500.0,
        "Australia": 70.0, "Canada": 65.0, "Germany": 45.0,
        "France": 45.0, "Singapore": 60.0, "UAE": 150.0,
    }
    _SEO_DEFAULTS = {
        "United States": 1500.0, "United Kingdom": 1200.0, "India": 50000.0,
        "Australia": 1800.0, "Canada": 1600.0, "Germany": 1400.0,
        "France": 1400.0, "Singapore": 1300.0, "UAE": 2000.0,
    }

    with col_a:
        st.subheader("Website Info")
        client_url = st.text_input(
            "Client Website URL *",
            value=st.session_state.get("client_url", ""),
            placeholder="example.com",
        )
        niche = st.text_input(
            "Industry / Niche *",
            value=st.session_state.get("niche", ""),
            placeholder="e.g. Women's Clothing, Power Tools, Supplements",
        )
        location = st.selectbox(
            "Target Country",
            ["United States", "United Kingdom", "India", "Australia", "Canada",
             "Germany", "France", "Singapore", "UAE"],
        )

    currency_symbol, currency_code = _CURRENCY.get(location, ("$", "USD"))
    default_aov     = _AOV_DEFAULTS.get(location, 50.0)
    default_seo     = _SEO_DEFAULTS.get(location, 1500.0)

    with col_b:
        st.subheader(f"ROI Parameters ({currency_code})")
        aov = st.number_input(
            f"Average Order Value (AOV) {currency_symbol}",
            min_value=0.0,
            value=float(st.session_state.get("aov", default_aov) if st.session_state.get("location") == location else default_aov),
            step=100.0 if currency_symbol == "₹" else 5.0,
            help="Average revenue per completed order",
        )
        monthly_seo_cost = st.number_input(
            f"Monthly SEO Investment {currency_symbol}",
            min_value=0.0,
            value=float(st.session_state.get("monthly_seo_cost", default_seo) if st.session_state.get("location") == location else default_seo),
            step=5000.0 if currency_symbol == "₹" else 100.0,
        )
        conv_rate_pct = st.slider(
            "E-commerce Conversion Rate %",
            min_value=0.5, max_value=5.0,
            value=float(st.session_state.get("conv_rate_pct", 2.0)),
            step=0.1,
        )
        target_traffic = st.number_input(
            "Target Monthly Traffic (Achievable)",
            min_value=0,
            value=int(st.session_state.get("target_traffic", 0)),
            step=5000,
            help="Your realistic traffic target for this prospect. Leave 0 to auto-calculate as 10% of competitor traffic.",
        )

    if st.button("💾 Save & Continue →", type="primary", key="btn_save_setup"):
        if not client_url.strip():
            st.error("Client URL is required.")
        elif not niche.strip():
            st.error("Niche is required.")
        else:
            st.session_state.client_url       = client_url.strip()
            st.session_state.niche            = niche.strip()
            st.session_state.location         = location
            st.session_state.aov              = aov
            st.session_state.monthly_seo_cost = monthly_seo_cost
            st.session_state.conv_rate_pct    = conv_rate_pct
            st.session_state.conv_rate        = conv_rate_pct / 100
            st.session_state.currency_symbol  = currency_symbol
            st.session_state.currency_code    = currency_code
            st.session_state.target_traffic   = target_traffic
            st.success(f"✅ Setup saved for **{client_url.strip()}**. Go to Tab 2.")

    if st.session_state.get("client_url"):
        st.divider()
        sym = st.session_state.get("currency_symbol", "$")
        st.caption(
            f"Current: **{st.session_state.client_url}** | "
            f"Niche: {st.session_state.get('niche')} | "
            f"AOV: {sym}{st.session_state.get('aov')} | "
            f"CR: {st.session_state.get('conv_rate_pct')}%"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Find Competitors
# ═══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.header("Find Competitors")

    if not st.session_state.get("client_url"):
        st.warning("Complete Step 1 first.")
    else:
        client_url_now = st.session_state.client_url
        location_now   = st.session_state.get("location", "United States")
        niche_now      = st.session_state.get("niche", "")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 1 — Read the website
        # ─────────────────────────────────────────────────────────────────────
        st.markdown("### Step 1 — Read the Website")
        st.caption(
            "We visit the client site and detect what specific products or services it sells, "
            "by reading the navigation, URL structure, and page headings."
        )

        if st.button("🌐 Read Website & Detect Products", type="primary",
                     key="btn_scrape", use_container_width=True):
            with st.spinner(f"Reading {client_url_now}…"):
                scrape_result = scrape_product_terms(client_url_now)
            st.session_state.scrape_result    = scrape_result
            st.session_state["_scraped_url"]  = client_url_now
            # Clear old keywords so step 2 starts fresh
            st.session_state.pop("keywords_raw", None)

        scrape_result = st.session_state.get("scrape_result")
        if scrape_result and st.session_state.get("_scraped_url") == client_url_now:
            terms = scrape_result.get("product_terms", [])
            if scrape_result.get("error") and not terms:
                st.warning(
                    f"⚠️ {scrape_result['error']}  \n"
                    "The site is likely JS-rendered. You can still proceed — "
                    "Step 2 will use your **niche** to pull real keywords from Google instead."
                )
            elif terms:
                st.success(f"✅ Detected **{len(terms)}** product/service categories")
                cols = st.columns(4)
                for i, t in enumerate(terms):
                    cols[i % 4].markdown(f"• {t.title()}")

        st.divider()

        # ─────────────────────────────────────────────────────────────────────
        # STEP 2 — Generate real keywords via Google Autocomplete
        # ─────────────────────────────────────────────────────────────────────
        st.markdown("### Step 2 — Generate Real Keywords from Google")
        st.caption(
            "We feed the detected product terms into **Google Autocomplete** — the same "
            "suggestions Google shows real buyers as they type. These are guaranteed to have "
            "search volume. No Claude API needed."
        )

        if st.button("🔑 Generate Keywords from Google Autocomplete", type="primary",
                     key="btn_autocomplete", use_container_width=True):
            if not serp_key:
                st.error("Add your SearchAPI key in the sidebar first.")
            else:
                terms = (st.session_state.get("scrape_result") or {}).get("product_terms", [])
                with st.spinner("Asking Google Autocomplete for real buyer queries…"):
                    kws = get_real_keywords_from_autocomplete(
                        product_terms=terms,
                        serp_api_key=serp_key,
                        location=location_now,
                        fallback_niche=niche_now,
                    )
                if kws:
                    st.session_state.keywords_raw = "\n".join(kws)
                    st.success(f"✅ Got **{len(kws)}** real search queries from Google Autocomplete")
                else:
                    st.warning("Autocomplete returned nothing — type keywords manually below.")

        # Editable keyword box
        keywords_raw = st.text_area(
            "Keywords — review and edit before searching (one per line)",
            value=st.session_state.get("keywords_raw", ""),
            height=200,
            key="kw_input_primary",
            placeholder=(
                "Click the button above to auto-fill from Google Autocomplete.\n\n"
                "Or type manually, e.g.:\nnon stick kadai\npressure cooker 5 litre\nhard anodised cookware"
            ),
        )

        st.divider()

        # ─────────────────────────────────────────────────────────────────────
        # STEP 3 — Find Competitors on Google SERP
        # ─────────────────────────────────────────────────────────────────────
        st.markdown("### Step 3 — Find Competitors on Google")
        st.caption(
            "We search Google for each keyword and rank the domains that consistently appear "
            "across multiple queries — those are your real SEO competitors."
        )

        col_a, col_b = st.columns(2)
        with col_a:
            min_freq = st.slider(
                "Min keyword overlap (domain must rank for ≥ N keywords)",
                min_value=1, max_value=5, value=2,
                help="Higher = fewer but more confident competitors.",
            )
        with col_b:
            num_results = st.slider(
                "SERP depth per keyword", 5, 15, 10,
                help="How many top Google positions to scan per keyword.",
            )

        if st.button("🔍 Find Competitors", type="primary",
                     key="btn_find_comps", use_container_width=True):
            if not serp_key:
                st.error("Add your SearchAPI key in the sidebar first.")
            elif not keywords_raw.strip():
                st.error("No keywords yet — complete Steps 1 & 2 first.")
            else:
                kws = [k.strip() for k in keywords_raw.splitlines() if k.strip()]
                st.session_state.keywords_raw = keywords_raw

                effective_min = min(min_freq, max(1, len(kws) // 2))
                if effective_min < min_freq:
                    st.info(f"Only {len(kws)} keywords — relaxing min overlap from {min_freq} → {effective_min}.")

                client_domain = (
                    client_url_now.replace("https://", "").replace("http://", "")
                    .replace("www.", "").split("/")[0].strip().lower()
                )

                with st.spinner(f"Searching Google for {len(kws)} keywords…"):
                    try:
                        comps, errs = fetch_competitors(
                            kws, serp_key, location_now,
                            num_results, min_frequency=effective_min,
                        )
                        comps = [c for c in comps if client_domain not in c["domain"]]
                        st.session_state.discovered_competitors = comps
                        st.session_state.serp_keywords_used     = kws
                        if errs:
                            with st.expander(f"⚠️ {len(errs)} SERP error(s)"):
                                for e in errs:
                                    st.text(e)
                    except Exception as exc:
                        st.error(f"SearchAPI error: {exc}")
                        comps = []

                if comps:
                    st.success(f"✅ Found **{len(comps)}** competitor(s)")
                elif not st.session_state.get("discovered_competitors"):
                    st.warning(
                        "No competitors found. Try lowering the min overlap slider "
                        "or add more/broader keywords."
                    )

        # ── RESULTS TABLE ─────────────────────────────────────────────────────
        if st.session_state.get("discovered_competitors"):
            comps     = st.session_state.discovered_competitors
            total_kws = len(st.session_state.get("serp_keywords_used", []))

            st.divider()
            st.subheader(f"🏆 {len(comps)} Competitors Found")
            st.caption(
                "Ranked by SERP overlap — domains appearing across the most keywords "
                "are your most direct competitors."
            )

            rows = []
            for i, c in enumerate(comps[:30]):
                freq = c["frequency"]
                conf = int(round(freq / max(total_kws, 1) * 100))
                rows.append({
                    "#":             i + 1,
                    "Domain":        c["domain"],
                    "Overlap":       f"{freq} / {total_kws} keywords",
                    "Confidence":    f"{conf}%",
                    "Avg Position":  c.get("avg_position", "—"),
                    "Best Position": c.get("best_position", "—"),
                    "Ranks For":     ", ".join(c["keywords_found_in"][:4])
                                     + ("…" if len(c["keywords_found_in"]) > 4 else ""),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.markdown("**Select up to 5 competitors for deep Ahrefs analysis:**")
            valid_options = [c["domain"] for c in comps[:30]]
            prev_sel      = st.session_state.get("selected_competitors", [])
            safe_default  = [d for d in prev_sel if d in valid_options] or valid_options[:3]
            selections = st.multiselect(
                "Competitors",
                options=valid_options,
                default=safe_default[:5],
                key="comp_multiselect",
                max_selections=5,
                label_visibility="collapsed",
            )
            st.session_state.selected_competitors = selections
            if selections:
                st.success(
                    f"✅ **{len(selections)} competitor(s) locked in** "
                    "→ go to Tab 3 to upload their Ahrefs CSVs"
                )

        # ── MANUAL OVERRIDE ───────────────────────────────────────────────────
        st.divider()
        with st.expander("➕ Already know your competitors? Add them manually", expanded=False):
            st.caption("Skip the keyword search and enter competitor domains directly.")
            manual_raw = st.text_area(
                "One domain per line",
                value=st.session_state.get("manual_competitors_raw", ""),
                placeholder="milton.in\nttkprestige.com\nborosil.com",
                height=100, key="manual_comp_input",
            )
            if st.button("➕ Add to list", key="btn_add_manual"):
                manual_domains = [
                    d.strip().replace("https://", "").replace("http://", "")
                     .replace("www.", "").split("/")[0].lower()
                    for d in manual_raw.splitlines() if d.strip()
                ]
                existing = st.session_state.get("discovered_competitors", [])
                existing_domains = {c["domain"] for c in existing}
                added = 0
                for d in manual_domains:
                    if d and d not in existing_domains:
                        existing.append({
                            "domain": d, "frequency": 0,
                            "avg_position": "—", "best_position": "—",
                            "keywords_found_in": ["manual"],
                        })
                        existing_domains.add(d)
                        added += 1
                st.session_state.discovered_competitors = existing
                st.session_state.manual_competitors_raw = manual_raw
                current_sel = st.session_state.get("selected_competitors", [])
                for d in manual_domains:
                    if d and d not in current_sel:
                        current_sel.append(d)
                st.session_state.selected_competitors = current_sel
                st.success(f"✅ Added {added} competitor(s).")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Upload Ahrefs Data
# ═══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.header("Upload Ahrefs Data Dumps")
    st.caption(
        "Export from Ahrefs → Site Explorer → **Top Pages** or **Organic Keywords** → Export CSV. "
        "Upload client data plus one CSV per competitor."
    )
    with st.expander("ℹ️ Which CSV enables which analysis?", expanded=False):
        st.markdown(
            "| Upload | Enables |\n"
            "|--------|--------|\n"
            "| **Client — Organic Keywords CSV** | Keyword gap analysis, low-hanging fruit |\n"
            "| **Client — Top Pages CSV** | Client traffic benchmark only |\n"
            "| **Competitor — Organic Keywords CSV** | Keyword gap analysis (find what they rank for that you don't) |\n"
            "| **Competitor — Top Pages CSV** | Competitor traffic benchmark + top pages to replicate |\n\n"
            "**Tip:** For the richest analysis, upload Organic Keywords CSVs for both client and competitors."
        )

    selected_comps = st.session_state.get("selected_competitors", [])

    # ── client ────────────────────────────────────────────────────────────────
    st.subheader("📊 Client Data")
    c1, c2 = st.columns(2)

    with c1:
        f = st.file_uploader("Client — Top Pages CSV", type="csv", key="up_client_pages")
        if f:
            try:
                df = parse_top_pages(f)
                st.session_state.client_pages_df = df
                t = estimate_traffic(df)
                st.success(f"✅ {len(df):,} pages | Traffic: {t:,}/mo")
                with st.expander("Detected columns"):
                    st.write(list(df.columns))
            except Exception as e:
                st.error(f"Parse error: {e}")

    with c2:
        f = st.file_uploader("Client — Organic Keywords CSV", type="csv", key="up_client_kws")
        if f:
            try:
                df = parse_organic_keywords(f)
                st.session_state.client_kw_df = df
                t = estimate_traffic(df)
                st.success(f"✅ {len(df):,} keywords loaded | Traffic: {t:,}/mo")
                with st.expander("Detected columns"):
                    st.write(list(df.columns))
            except Exception as e:
                st.error(f"Parse error: {e}")

    st.divider()

    # ── competitors ───────────────────────────────────────────────────────────
    if not selected_comps:
        st.info("Complete Step 2 to select competitors, then upload their CSVs here.")
    else:
        st.subheader("🏆 Competitor Data")
        comp_dfs = st.session_state.get("comp_dfs", {})

        for domain in selected_comps[:6]:
            with st.expander(f"📁  {domain}", expanded=False):
                ca, cb = st.columns(2)
                with ca:
                    f = st.file_uploader("Organic Keywords CSV", type="csv",
                                         key=f"up_comp_kw_{domain}")
                    if f:
                        try:
                            df = parse_organic_keywords(f)
                            comp_dfs[domain] = df
                            t = estimate_traffic(df)
                            fmt = detect_format(df)
                            fmt_label = "Organic Keywords" if fmt == "organic_keywords" else "Top Pages"
                            st.success(f"✅ {len(df):,} rows | Traffic: {t:,}/mo | Detected: **{fmt_label}**")
                            if fmt == "top_pages":
                                st.info("Detected as Top Pages format — keyword gap analysis won't be available for this competitor. Upload Organic Keywords CSV for gap analysis.")
                        except Exception as e:
                            st.error(f"Parse error: {e}")
                with cb:
                    f2 = st.file_uploader("Top Pages CSV (optional)", type="csv",
                                          key=f"up_comp_pages_{domain}")
                    if f2:
                        try:
                            df2 = parse_top_pages(f2)
                            comp_dfs[f"{domain}__pages"] = df2
                            t = estimate_traffic(df2)
                            st.success(f"✅ {len(df2):,} pages | Traffic: {t:,}/mo")
                        except Exception as e:
                            st.error(f"Parse error: {e}")

        st.session_state.comp_dfs = comp_dfs

        loaded = [d for d in selected_comps if d in comp_dfs]
        if loaded:
            st.success(f"✅ Data loaded for {len(loaded)} competitor(s): {', '.join(loaded)} → go to Tab 4")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Analysis & Report
# ═══════════════════════════════════════════════════════════════════════════════

with tab4:
    st.header("SEO Potential Analysis Report")

    if not st.session_state.get("client_url"):
        st.warning("Complete Steps 1–3 first.")
        st.stop()

    # summary row
    meta_cols = st.columns(4)
    meta_cols[0].markdown(f"**Client:** {st.session_state.get('client_url')}")
    meta_cols[1].markdown(f"**Niche:** {st.session_state.get('niche', '—')}")
    meta_cols[2].markdown(f"**AOV:** {st.session_state.get('currency_symbol','$')}{st.session_state.get('aov', '—')}")
    meta_cols[3].markdown(
        f"**Competitors:** {len(st.session_state.get('selected_competitors', []))} selected | "
        f"{len([k for k in st.session_state.get('comp_dfs', {}).keys() if '__pages' not in k])} with data"
    )

    st.divider()

    # ── data status check ─────────────────────────────────────────────────────
    with st.expander("🔎 Data Status (check before running)", expanded=True):
        client_kw_df_check = st.session_state.get("client_kw_df")
        comp_dfs_check     = st.session_state.get("comp_dfs", {})

        st.markdown("**Client Keywords CSV:**")
        if client_kw_df_check is not None:
            cols = list(client_kw_df_check.columns)
            kw_c  = _af(client_kw_df_check, "keyword", "keywords", "query")
            pos_c = _af(client_kw_df_check, "position", "current_position", "pos", "rank")
            vol_c = _af(client_kw_df_check, "volume", "search_volume")
            trf_c = _af(client_kw_df_check, "traffic", "estimated_traffic")
            st.success(f"✅ {len(client_kw_df_check):,} rows loaded")
            st.write(f"Columns: `{cols}`")
            st.write(f"Keyword col: `{kw_c}` | Position col: `{pos_c}` | Volume col: `{vol_c}` | Traffic col: `{trf_c}`")
            st.dataframe(client_kw_df_check.head(3), use_container_width=True)
        else:
            st.warning("No client keywords CSV uploaded (Tab 3)")

        st.markdown("**Competitor CSVs:**")
        comp_domains = [d for d in comp_dfs_check if "__pages" not in d]
        if comp_domains:
            for d in comp_domains:
                df = comp_dfs_check[d]
                cols = list(df.columns)
                trf_c = _af(df, "traffic", "estimated_traffic", "organic_traffic")
                st.write(f"**{d}** — {len(df):,} rows | Traffic col: `{trf_c}` | Cols: `{cols}`")
                st.dataframe(df.head(2), use_container_width=True)
        else:
            st.warning("No competitor CSVs uploaded (Tab 3)")

    if st.button("🚀 Run Full SEO Potential Analysis", type="primary", use_container_width=True):

        prog  = st.progress(0, "Starting…")
        state = st.empty()
        results: dict = {}

        # ── 1. On-page audit ──────────────────────────────────────────────────
        state.text("Step 1 / 5 — On-page SEO audit…")
        prog.progress(10)
        try:
            analyzer    = SEOAnalyzer()
            site_result = analyzer.analyze(st.session_state.client_url)
        except Exception as exc:
            site_result = None
            st.warning(f"Crawl failed: {exc}")
        results["site_result"] = site_result

        # ── 2 & 3. Full Ahrefs analysis ───────────────────────────────────────
        state.text("Step 2 / 4 — Analysing Ahrefs data dumps…")
        prog.progress(30)

        comp_dfs_all = st.session_state.get("comp_dfs", {})
        client_kw_df = st.session_state.get("client_kw_df")

        comp_kw_dfs    = {d: comp_dfs_all[d] for d in st.session_state.get("selected_competitors", []) if d in comp_dfs_all}
        comp_pages_dfs = {d.replace("__pages", ""): comp_dfs_all[d] for d in comp_dfs_all if "__pages" in d}

        ahrefs = {}
        if client_kw_df is not None:
            state.text("Step 2 / 4 — Running keyword gap + low-hanging fruit analysis…")
            prog.progress(50)
            try:
                ahrefs = full_analysis(client_kw_df, comp_kw_dfs, comp_pages_dfs)
            except Exception as exc:
                st.warning(f"Ahrefs analysis error: {exc}")
                ahrefs = {}
        else:
            # No client keywords uploaded — still get competitor traffic
            for domain, df in {**comp_kw_dfs, **comp_pages_dfs}.items():
                t = estimate_traffic(df)
                ahrefs.setdefault("comp_traffic", {})[domain] = t
            ahrefs["total_comp_traffic"] = sum(ahrefs.get("comp_traffic", {}).values())

        results["ahrefs"] = ahrefs

        # ── 3. ROI ────────────────────────────────────────────────────────────
        state.text("Step 3 / 4 — Calculating SEO ROI…")
        prog.progress(70)
        total_traffic = ahrefs.get("total_comp_traffic", 0)
        roi = calculate_roi(
            competitor_traffic=total_traffic,
            achievable_fraction=0.10,
            aov=st.session_state.get("aov", 50.0),
            conversion_rate=st.session_state.get("conv_rate", 0.02),
            monthly_seo_cost=st.session_state.get("monthly_seo_cost", 1500.0),
            target_traffic=int(st.session_state.get("target_traffic", 0)),
        )
        results["roi"]           = roi
        results["total_traffic"] = total_traffic
        results["comp_traffic"]  = ahrefs.get("comp_traffic", {})

        # ── 4. Scoring (rule-based) ───────────────────────────────────────────
        state.text("Step 4 / 4 — Scoring SEO potential…")
        prog.progress(85)

        gap_count       = len(ahrefs.get("keyword_gaps", pd.DataFrame()))
        low_hang_count  = len(ahrefs.get("low_hanging_fruit", pd.DataFrame()))
        client_traffic  = ahrefs.get("client_total_traffic", 0)

        if total_traffic >= 10000 and (gap_count >= 10 or low_hang_count >= 5) and roi["is_viable"]:
            potential_verdict = "HIGH"
            summary = (
                f"Strong SEO potential. Competitors drive {total_traffic:,} organic visits/month. "
                f"Found {gap_count} keyword gaps and {low_hang_count} low-hanging-fruit keywords. "
                f"ROI is viable at {roi['roi_pct']}% annually."
            )
        elif total_traffic >= 3000 or gap_count >= 5 or low_hang_count >= 3:
            potential_verdict = "MEDIUM"
            summary = (
                f"Moderate SEO potential. Competitors drive {total_traffic:,} visits/month. "
                f"Found {gap_count} keyword gaps and {low_hang_count} quick-win opportunities. "
                f"{'ROI viable.' if roi['is_viable'] else 'ROI marginal — verify AOV.'}"
            )
        else:
            potential_verdict = "LOW"
            summary = (
                f"Limited SEO potential. Combined competitor traffic is only {total_traffic:,}/month "
                f"with {gap_count} keyword gaps found. May not justify SEO investment at this stage."
            )

        ai_result = {"potential": potential_verdict, "summary": summary, "actions": []}
        results["ai_result"] = ai_result
        prog.progress(100, "Done ✅")
        state.empty()
        st.session_state.last_results = results

    # ── display results ────────────────────────────────────────────────────────
    if not st.session_state.get("last_results"):
        st.info("Click **Run Full SEO Potential Analysis** to generate the report.")
        st.stop()

    R            = st.session_state.last_results
    ai_result    = R.get("ai_result", {})
    site_result  = R.get("site_result")
    roi          = R.get("roi", {})
    comp_traffic = R.get("comp_traffic", {})
    ahrefs       = R.get("ahrefs", {})
    all_gaps     = ahrefs.get("keyword_gaps", pd.DataFrame())
    low_hanging  = ahrefs.get("low_hanging_fruit", pd.DataFrame())
    top_pages    = ahrefs.get("top_comp_pages", pd.DataFrame())

    # ── VERDICT BANNER ─────────────────────────────────────────────────────────
    potential = ai_result.get("potential", "MEDIUM")
    icon  = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "❄️"}.get(potential, "?")
    color = {"HIGH": "green", "MEDIUM": "orange", "LOW": "blue"}.get(potential, "gray")

    st.markdown(f"## {icon} SEO Potential: <span style='color:{color};font-weight:700'>{potential}</span>",
                unsafe_allow_html=True)

    if ai_result.get("summary"):
        st.info(ai_result["summary"])

    if ai_result.get("actions"):
        st.subheader("✅ Recommended Actions")
        for action in ai_result["actions"]:
            st.markdown(f"- {action}")

    st.divider()

    # ── ROI ────────────────────────────────────────────────────────────────────
    st.subheader("💰 SEO ROI Estimate")
    r1, r2, r3, r4 = st.columns(4)
    sym = st.session_state.get("currency_symbol", "$")
    _tgt = int(st.session_state.get("target_traffic", 0))
    r1.metric("Competitor Traffic",    f"{R.get('total_traffic', 0):,}/mo")
    r2.metric("Target Traffic" if _tgt > 0 else "Achievable (10%)",
              f"{roi.get('achievable_traffic', 0):,}/mo",
              delta="Custom target" if _tgt > 0 else "10% of comp traffic",
              delta_color="off")
    r3.metric("Est. Monthly Revenue",  f"{sym}{roi.get('monthly_revenue', 0):,.0f}")
    r4.metric("Annual ROI",            f"{roi.get('roi_pct', 0)}%",
              delta="Viable ✅" if roi.get("is_viable") else "Low ❌",
              delta_color="normal")

    st.divider()

    # ── COMPETITOR TRAFFIC ─────────────────────────────────────────────────────
    if comp_traffic:
        st.subheader("🏆 Competitor Traffic Benchmark")
        client_traffic = ahrefs.get("client_total_traffic", 0)
        comp_rows = [{"Competitor": d, "Est. Organic Traffic / Month": f"{t:,}", "_t": t}
                     for d, t in sorted(comp_traffic.items(), key=lambda x: -x[1])]
        if client_traffic:
            comp_rows.insert(0, {"Competitor": f"⭐ {st.session_state.get('client_url')} (Client)",
                                  "Est. Organic Traffic / Month": f"{client_traffic:,}", "_t": client_traffic})
        comp_df = pd.DataFrame(comp_rows).drop(columns=["_t"])
        st.dataframe(comp_df, use_container_width=True, hide_index=True)
        st.divider()

    # ── KEYWORD GAPS ───────────────────────────────────────────────────────────
    has_kw_data = ahrefs.get("has_keyword_gap_data", False)
    if not all_gaps.empty:
        st.subheader(f"🔑 Keyword Gaps — {len(all_gaps):,} opportunities")
        st.caption("Keywords competitors rank for (top 20) that you don't rank for or rank below position 20.")
        col_rename = {
            "keyword":             "Keyword",
            "search_volume":       "Search Volume",
            "competitor":          "Best Competitor",
            "competitor_position": "Comp. Position",
            "client_position":     "Your Position",
            "opportunity_score":   "Opportunity Score",
        }
        display_cols = [c for c in col_rename if c in all_gaps.columns]
        st.dataframe(
            all_gaps[display_cols].head(50).rename(columns=col_rename),
            use_container_width=True, hide_index=True,
        )
        st.divider()
    else:
        st.subheader("🔑 Keyword Gaps")
        comp_dfs_loaded = st.session_state.get("comp_dfs", {})
        all_top_pages = all(
            detect_format(df) == "top_pages"
            for d, df in comp_dfs_loaded.items()
            if "__pages" not in d
        ) if comp_dfs_loaded else True
        if all_top_pages and comp_dfs_loaded:
            st.info(
                "**Keyword gap analysis requires Organic Keywords CSVs for competitors.**\n\n"
                "Your competitor uploads are in **Top Pages** format, which shows traffic per page "
                "but not individual keywords. To see which keywords competitors rank for that you don't:\n\n"
                "1. Go to Ahrefs → Site Explorer → enter competitor domain\n"
                "2. Click **Organic Keywords** in the left menu\n"
                "3. Export as CSV and re-upload in Tab 3\n\n"
                "Top Pages CSVs are still used for the traffic benchmark and top pages sections below."
            )
        elif st.session_state.get("client_kw_df") is None:
            st.info("Upload your **Client Organic Keywords CSV** in Tab 3 to enable keyword gap analysis.")
        else:
            st.info("No keyword gaps found with the current data and filters (min volume: 100, competitor position ≤ 20).")
        st.divider()

    # ── LOW-HANGING FRUIT ──────────────────────────────────────────────────────
    if not low_hanging.empty:
        st.subheader(f"🍋 Low-Hanging Fruit — {len(low_hanging):,} keywords")
        st.caption("You already rank positions 11–30. Push these to top 10 for quick traffic wins.")
        lh_rename = {
            "keyword":          "Keyword",
            "current_position": "Your Position",
            "search_volume":    "Search Volume",
            "traffic_if_top5":  "Est. Traffic if Top 5",
            "priority_score":   "Priority Score",
        }
        display_cols = [c for c in lh_rename if c in low_hanging.columns]
        st.dataframe(
            low_hanging[display_cols].head(30).rename(columns=lh_rename),
            use_container_width=True, hide_index=True,
        )
        st.divider()

    # ── TOP COMPETITOR PAGES ───────────────────────────────────────────────────
    if not top_pages.empty:
        st.subheader("📄 Top Competitor Pages by Traffic")
        st.caption("High-traffic pages you can create competing content for.")
        tp_rename = {
            "competitor":  "Competitor",
            "url":         "Page URL",
            "traffic":     "Est. Traffic / Month",
            "top_keyword": "Top Keyword",
        }
        display_cols = [c for c in tp_rename if c in top_pages.columns]
        st.dataframe(
            top_pages[display_cols].head(20).rename(columns=tp_rename),
            use_container_width=True, hide_index=True,
        )
        st.divider()

    # ── STRATEGIC RECOMMENDATIONS ──────────────────────────────────────────────
    from services.strategic_advisor import build_strategic_recommendations
    st.subheader("🎯 Strategic Recommendations")
    strat_recs = build_strategic_recommendations(ahrefs, site_result)
    priority_color = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}
    for rec in strat_recs:
        icon = priority_color.get(rec["priority"], "⚪")
        with st.expander(f"{icon} {rec['title']} — {rec['priority']} Priority", expanded=True):
            st.caption(rec["rationale"])
            for action in rec["actions"]:
                st.markdown(f"- {action}")

    # ── ON-PAGE AUDIT (compact) ────────────────────────────────────────────────
    if site_result:
        st.divider()
        st.subheader("🔍 On-Page Health Check")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Health Score",    f"{site_result.health_score:.0f} / 100")
        a2.metric("Potential Score", f"{site_result.potential_score:.0f} / 100")
        a3.metric("Checks Passed",   site_result.key_signals.get("checks_passed", 0))
        a4.metric("Checks Failed",   site_result.key_signals.get("checks_failed", 0))
        sig = site_result.key_signals
        issues = []
        if not sig.get("uses_https"):      issues.append("❌ No HTTPS")
        if sig.get("load_time_s", 0) >= 3: issues.append(f"⚠️ Slow ({sig['load_time_s']}s)")
        if not sig.get("meta_desc_len"):   issues.append("⚠️ No meta description")
        if sig.get("h1_count", 0) != 1:   issues.append(f"⚠️ {sig.get('h1_count',0)} H1 tag(s)")
        if not sig.get("has_sitemap"):     issues.append("⚠️ No sitemap.xml")
        if not sig.get("has_schema"):      issues.append("⚠️ No schema markup")
        if sig.get("img_no_alt", 0) > 0:  issues.append(f"⚠️ {sig['img_no_alt']} images without alt")
        if issues:
            st.markdown("**Issues:** " + "  |  ".join(issues))

    # ── EXPORT ─────────────────────────────────────────────────────────────────
    st.divider()
    try:
        word_bytes = generate_word_report(
            client_url      = st.session_state.get("client_url", ""),
            niche           = st.session_state.get("niche", ""),
            location        = st.session_state.get("location", ""),
            currency_symbol = st.session_state.get("currency_symbol", "$"),
            ai_result       = ai_result,
            roi             = roi,
            comp_traffic    = comp_traffic,
            ahrefs          = ahrefs,
            site_result     = site_result,
        )
        st.download_button(
            label="📄 Download Full Report (Word)",
            data=word_bytes,
            file_name=f"seo_report_{st.session_state.get('client_url','report').replace('https://','').replace('http://','').replace('/','_')}_{datetime.now().strftime('%Y%m%d')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
            type="primary",
        )
    except Exception as e:
        st.error(f"Word generation failed: {e}")
