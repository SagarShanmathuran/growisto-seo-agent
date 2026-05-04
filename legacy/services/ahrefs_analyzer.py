"""Parse Ahrefs CSV exports and run comprehensive SEO analysis."""

import pandas as pd
from io import StringIO


# ── CSV loading ───────────────────────────────────────────────────────────────

def _load(file) -> pd.DataFrame:
    if hasattr(file, "read"):
        raw_bytes = file.read()
    else:
        with open(file, "rb") as fh:
            raw_bytes = fh.read()

    # UTF-16 detection (BOM)
    if raw_bytes[:2] in (b'\xff\xfe', b'\xfe\xff'):
        raw = raw_bytes.decode("utf-16", errors="replace")
    else:
        raw = raw_bytes.decode("utf-8-sig", errors="replace")

    lines = raw.splitlines()

    # Detect separator from first non-empty line
    sep = "\t"
    for line in lines[:5]:
        if line.strip():
            sep = "\t" if line.count("\t") >= line.count(",") else ","
            break

    # Find real header row (skip Ahrefs metadata lines)
    skip_starts = ("current view", "exported", "https://", "http://")
    header_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(sep)
        if len(parts) >= 3 and not any(stripped.lower().startswith(s) for s in skip_starts):
            header_idx = i
            break

    csv_body = "\n".join(lines[header_idx:])
    try:
        return pd.read_csv(StringIO(csv_body), sep=sep, on_bad_lines="skip")
    except TypeError:
        return pd.read_csv(StringIO(csv_body), sep=sep, error_bad_lines=False)


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        c.strip().lower()
         .replace(" ", "_").replace(".", "_").replace(":", "_")
         .replace("(", "").replace(")", "").replace("%", "pct")
        for c in df.columns
    ]
    return df


def _find(df: pd.DataFrame, *candidates: str) -> str | None:
    cols = list(df.columns)
    for c in candidates:
        if c.lower() in cols:
            return c.lower()
    for c in candidates:
        for col in cols:
            if c.lower() in col:
                return col
    return None


def _safe_int(val) -> int:
    try:
        f = float(val)
        return 0 if (f != f) else int(f)   # NaN check: NaN != NaN
    except (ValueError, TypeError):
        return 0


# ── public parsers ────────────────────────────────────────────────────────────

def parse_top_pages(file) -> pd.DataFrame:
    return _norm(_load(file))


def parse_organic_keywords(file) -> pd.DataFrame:
    return _norm(_load(file))


def detect_format(df: pd.DataFrame) -> str:
    """Return 'top_pages' or 'organic_keywords' based on columns present."""
    cols = " ".join(df.columns)
    if "top_keyword" in cols or ("url" in cols and "traffic" in cols and "keyword" not in cols):
        return "top_pages"
    return "organic_keywords"


# ── traffic estimation ────────────────────────────────────────────────────────

def estimate_traffic(df: pd.DataFrame) -> int:
    fmt = detect_format(df)
    if fmt == "top_pages":
        col = _find(df, "traffic", "organic_traffic", "estimated_traffic")
    else:
        # Organic keywords: prefer current over previous
        col = _find(df, "current_organic_traffic", "organic_traffic",
                    "traffic", "estimated_traffic")
    if col is None:
        return 0
    return _safe_int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


# ── comprehensive analysis ────────────────────────────────────────────────────

def full_analysis(
    client_kw_df: pd.DataFrame,
    comp_dfs: dict[str, pd.DataFrame],
    comp_pages_dfs: dict[str, pd.DataFrame],
    min_volume: int = 100,
) -> dict:
    """
    Full SEO gap analysis.
    Handles two formats automatically:
      - Organic Keywords CSV  → keyword gaps + low-hanging fruit
      - Top Pages CSV         → competitor traffic + top pages
    """

    # ── client keyword columns ────────────────────────────────────────────────
    cli_kw_col  = _find(client_kw_df, "keyword", "keywords", "query")
    cli_pos_col = _find(client_kw_df, "current_position", "position", "pos", "rank")
    cli_vol_col = _find(client_kw_df, "volume", "search_volume")
    cli_trf_col = _find(client_kw_df, "current_organic_traffic", "organic_traffic",
                        "traffic", "estimated_traffic")

    # Build client keyword map
    client_kws: dict[str, dict] = {}
    if cli_kw_col:
        for _, row in client_kw_df.iterrows():
            kw  = str(row[cli_kw_col]).lower().strip()
            pos = _safe_int(row.get(cli_pos_col, 999)) or 999
            vol = _safe_int(row.get(cli_vol_col, 0))
            trf = _safe_int(row.get(cli_trf_col, 0))
            if kw and pos > 0:
                if kw not in client_kws or pos < client_kws[kw]["position"]:
                    client_kws[kw] = {"position": pos, "volume": vol, "traffic": trf}

    client_total_traffic = sum(d["traffic"] for d in client_kws.values())

    # ── competitor traffic ─────────────────────────────────────────────────────
    comp_traffic: dict[str, int] = {}

    # From top-pages CSVs (most accurate)
    for domain, df in comp_pages_dfs.items():
        comp_traffic[domain] = estimate_traffic(df)

    # From organic keyword CSVs (fallback or supplement)
    for domain, df in comp_dfs.items():
        if domain not in comp_traffic or comp_traffic[domain] == 0:
            comp_traffic[domain] = estimate_traffic(df)

    # Also check if any comp_dfs are actually top_pages format
    for domain, df in comp_dfs.items():
        if detect_format(df) == "top_pages":
            comp_pages_dfs[domain] = df   # treat as pages

    total_comp_traffic = sum(comp_traffic.values())

    # ── keyword gap analysis (only if comp has organic keyword data) ───────────
    gaps: list[dict] = []
    seen_gaps: set[str] = set()

    for domain, df in comp_dfs.items():
        if detect_format(df) == "top_pages":
            continue   # skip — no keyword-level data

        comp_kw_col  = _find(df, "keyword", "keywords", "query")
        comp_pos_col = _find(df, "current_position", "position", "pos", "rank")
        comp_vol_col = _find(df, "volume", "search_volume")
        comp_trf_col = _find(df, "current_organic_traffic", "organic_traffic",
                             "traffic", "estimated_traffic")

        if not comp_kw_col:
            continue

        for _, row in df.iterrows():
            kw       = str(row[comp_kw_col]).lower().strip()
            comp_pos = _safe_int(row.get(comp_pos_col, 999)) or 999
            comp_vol = _safe_int(row.get(comp_vol_col, 0))
            comp_trf = _safe_int(row.get(comp_trf_col, 0))

            if not kw or comp_pos > 20 or comp_vol < min_volume:
                continue

            cli_data = client_kws.get(kw, {})
            cli_pos  = cli_data.get("position", 999)
            if cli_pos <= 20:
                continue

            opp = round(comp_vol / max(comp_pos, 1), 1)
            if kw not in seen_gaps:
                seen_gaps.add(kw)
                gaps.append({
                    "keyword":             kw,
                    "search_volume":       comp_vol,
                    "competitor":          domain,
                    "competitor_position": comp_pos,
                    "competitor_traffic":  comp_trf,
                    "client_position":     cli_pos if cli_pos < 999 else "Not ranking",
                    "opportunity_score":   opp,
                })

    gaps_df = (
        pd.DataFrame(gaps).sort_values("opportunity_score", ascending=False).reset_index(drop=True)
        if gaps else pd.DataFrame()
    )

    # ── low-hanging fruit (client ranks 11–30) ────────────────────────────────
    low_hanging: list[dict] = []
    if cli_kw_col and cli_pos_col:
        for kw, data in client_kws.items():
            pos = data["position"]
            vol = data["volume"]
            if 11 <= pos <= 30 and vol >= min_volume:
                low_hanging.append({
                    "keyword":          kw,
                    "current_position": pos,
                    "search_volume":    vol,
                    "traffic_if_top5":  _safe_int(vol * 0.15),
                    "priority_score":   round(vol / max(pos, 1), 1),
                })

    low_hanging_df = (
        pd.DataFrame(low_hanging).sort_values("priority_score", ascending=False).reset_index(drop=True)
        if low_hanging else pd.DataFrame()
    )

    # ── top competitor pages ───────────────────────────────────────────────────
    top_pages: list[dict] = []
    for domain, df in {**comp_pages_dfs, **{d: v for d, v in comp_dfs.items() if detect_format(v) == "top_pages"}}.items():
        url_col = _find(df, "url", "page", "address")
        trf_col = _find(df, "traffic", "organic_traffic", "estimated_traffic")
        kw_col  = _find(df, "top_keyword", "keyword")
        vol_col = _find(df, "top_keyword_volume", "top_keyword:_volume", "volume")

        if not (url_col and trf_col):
            continue
        for _, row in df.head(15).iterrows():
            t = _safe_int(row.get(trf_col, 0))
            if t > 0:
                top_pages.append({
                    "competitor":        domain,
                    "url":               str(row[url_col]),
                    "traffic":           t,
                    "top_keyword":       str(row[kw_col]) if kw_col else "",
                    "top_keyword_volume": _safe_int(row.get(vol_col, 0)) if vol_col else 0,
                })

    top_pages_df = (
        pd.DataFrame(top_pages).sort_values("traffic", ascending=False).reset_index(drop=True)
        if top_pages else pd.DataFrame()
    )

    has_keyword_data = len(gaps_df) > 0 or any(
        detect_format(df) == "organic_keywords" for df in comp_dfs.values()
    )

    return {
        "comp_traffic":           comp_traffic,
        "total_comp_traffic":     total_comp_traffic,
        "keyword_gaps":           gaps_df,
        "low_hanging_fruit":      low_hanging_df,
        "top_comp_pages":         top_pages_df,
        "client_total_traffic":   client_total_traffic,
        "client_total_keywords":  len(client_kws),
        "has_keyword_gap_data":   has_keyword_data,
        "gap_traffic_potential":  _safe_int(gaps_df["competitor_traffic"].sum()) if not gaps_df.empty and "competitor_traffic" in gaps_df.columns else 0,
        "low_hanging_potential":  _safe_int(low_hanging_df["traffic_if_top5"].sum()) if not low_hanging_df.empty else 0,
    }


# ── legacy shim ───────────────────────────────────────────────────────────────

def find_keyword_gaps(client_df, competitor_df, max_comp_position=20, min_volume=100):
    result = full_analysis(client_df, {"competitor": competitor_df}, {}, min_volume)
    return result["keyword_gaps"]
