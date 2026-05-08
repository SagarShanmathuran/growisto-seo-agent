"""
gap-analysis runner. Loads Ahrefs keyword CSVs for client + competitors, applies
intent + URL filters, computes gap keywords, picks Big Wins, writes a Word report.

Claude (in the chat) does the keyword-relevance reasoning. This script provides
two modes:

  - Default (no --in-scope-keywords): writes JSON listing all candidate gap kws
    for Claude to classify in chat.
  - --finalize with --in-scope-keywords PATH: regenerates the report using
    only the kws Claude marked in_scope.

Usage:
  python3 run.py --client-name VINOD --client-url vinodcookware.com \\
      --client-csv /path/client.csv \\
      --competitor "Milton:/path/milton.csv" \\
      --competitor "Borosil:/path/borosil.csv" \\
      [--business-model b2c_ecommerce] \\
      [--niche cookware] \\
      [--output-dir /tmp]
      [--in-scope-keywords /tmp/in-scope.json --finalize]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd


_NON_SERVICE_URL_RE = re.compile(
    r"/(blog|blogs|glossary|insights|resources|guide|guides|news|articles|"
    r"learn|help|support|careers|press|about|library|webinar|ebook|whitepaper)/",
    re.I,
)


# ── CSV loader (handles UTF-16 tab AND UTF-8 comma) ──────────────────────────

def _read_ahrefs_csv(path: str | Path) -> pd.DataFrame:
    for enc, sep in [("utf-16", "\t"), ("utf-8", ","), ("utf-8", "\t"), ("latin-1", ",")]:
        try:
            df = pd.read_csv(path, encoding=enc, sep=sep)
            if df.shape[1] > 1:
                return df
        except (UnicodeDecodeError, UnicodeError, pd.errors.ParserError):
            continue
    raise ValueError(f"Could not parse {path}")


def _normalise_kw_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename snapshot-format columns to comparison-format names we use downstream."""
    rename = {}
    for canonical, alts in {
        "Current organic traffic":  ["Organic traffic"],
        "Current position":         ["Position"],
        "Current URL":              ["URL"],
        "Organic traffic change":   ["Traffic change"],
    }.items():
        if canonical not in df.columns:
            for alt in alts:
                if alt in df.columns:
                    rename[alt] = canonical
                    break
    return df.rename(columns=rename) if rename else df


def load_keywords(path: str | Path) -> pd.DataFrame:
    df = _normalise_kw_columns(_read_ahrefs_csv(path))
    required = ["Keyword", "Branded", "Volume", "Current position", "Current organic traffic"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"CSV {path} missing columns: {missing}. Got: {list(df.columns)}")
    df["Current position"]        = pd.to_numeric(df["Current position"], errors="coerce")
    df["Volume"]                  = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
    df["Current organic traffic"] = pd.to_numeric(df["Current organic traffic"], errors="coerce").fillna(0)
    return df


# ── Intent + URL filter (from existing agent/) ───────────────────────────────

def _is_b2b(business_model: str) -> bool:
    bm = (business_model or "").lower()
    return bm.startswith("b2b") or bm in ("financial", "saas")


def _is_ecomm(business_model: str) -> bool:
    bm = (business_model or "").lower()
    return bm.startswith("b2c") or bm in ("ecommerce", "retail")


def _filter_intent_and_urls(df: pd.DataFrame, business_model: str) -> pd.DataFrame:
    """Drop info/blog kws + service-page-only filter for B2B/ecomm."""
    if not (_is_b2b(business_model) or _is_ecomm(business_model)):
        return df
    out = df
    if "Commercial" in out.columns and "Transactional" in out.columns:
        out = out[(out["Commercial"] == True) | (out["Transactional"] == True)]
    if "Current URL" in out.columns:
        mask = out["Current URL"].fillna("").astype(str).apply(
            lambda u: not bool(_NON_SERVICE_URL_RE.search(u)))
        out = out[mask]
    return out.copy()


# ── Gap-keyword computation ──────────────────────────────────────────────────

def compute_gap_keywords(client_df: pd.DataFrame,
                         comps: list[tuple[str, pd.DataFrame]],
                         min_gap_volume: int = 500,
                         max_gap_keywords: int = 30) -> list[dict]:
    client_ranks = dict(zip(client_df["Keyword"], client_df["Current position"]))
    gap_rows: dict[str, dict] = {}
    for name, cnb in comps:
        top10 = cnb[(cnb["Current position"] <= 10) & (cnb["Volume"] >= min_gap_volume)]
        for _, row in top10.iterrows():
            kw = row["Keyword"]
            client_pos = client_ranks.get(kw)
            client_pos_n = client_pos if pd.notna(client_pos) else 999
            if client_pos_n <= 20:
                continue
            comp_rank = int(row["Current position"])
            existing = gap_rows.get(kw)
            if existing and existing["competitor_rank"] <= comp_rank:
                continue
            gap_rows[kw] = {
                "keyword":            kw,
                "volume":             int(row["Volume"]),
                "best_competitor":    name,
                "competitor_rank":    comp_rank,
                "competitor_traffic": int(row.get("Current organic traffic", 0) or 0),
                "competitor_url":     str(row.get("Current URL", "") or ""),
                "client_rank":        "NR" if client_pos_n == 999 else str(int(client_pos_n)),
            }
    return sorted(gap_rows.values(), key=lambda x: -x["volume"])[:max_gap_keywords]


def _score_big_win(g: dict) -> float:
    score = g["competitor_traffic"]
    if g["competitor_rank"] > 1: score *= 1.2
    if g["competitor_rank"] > 3: score *= 1.1
    if g["client_rank"] != "NR":
        try:
            if 11 <= int(g["client_rank"]) <= 30:
                score *= 1.3
        except ValueError:
            pass
    return score


def big_wins(gap_kws: list[dict], top_n: int = 3) -> list[dict]:
    scored = sorted(gap_kws, key=_score_big_win, reverse=True)
    out = []
    for g in scored[:top_n]:
        if g["client_rank"] == "NR":
            pitch = (
                f"Build a page on '{g['keyword']}' (vol {g['volume']:,}/mo). "
                f"{g['best_competitor']} captures {g['competitor_traffic']:,} clicks/mo from this — "
                f"copy their structure at {g['competitor_url']}"
            )
        else:
            pitch = (
                f"Push '{g['keyword']}' from rank {g['client_rank']} to top 5. "
                f"{g['best_competitor']} (rank {g['competitor_rank']}) wins {g['competitor_traffic']:,} clicks/mo here."
            )
        out.append({**g, "pitch": pitch, "score": round(_score_big_win(g), 1)})
    return out


# ── Word report (compact 5-section format) ───────────────────────────────────

def write_report(out_path: Path,
                 client_name: str, client_url: str,
                 client_traffic: int,
                 comps: list[tuple[str, int]],
                 verdict_text: str,
                 gap_kws: list[dict], wins: list[dict],
                 achievable_top10: int,
                 misalignment: str = "",
                 niche: str = "General") -> None:
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    BRAND = RGBColor(0x36, 0x75, 0x88)
    DARK  = RGBColor(0x1A, 0x1A, 0x2E)
    GREY  = RGBColor(0x6B, 0x72, 0x80)
    RED   = RGBColor(0xDC, 0x26, 0x26)
    GREEN = RGBColor(0x05, 0x96, 0x69)

    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Cm(1.5)
        section.left_margin = section.right_margin = Cm(1.8)

    # Cover
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run("SEO POTENTIAL ANALYSIS")
    r.font.size = Pt(20); r.bold = True; r.font.color.rgb = BRAND

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rs = sub.add_run(f"{client_name}  ·  {niche}  ·  {datetime.now().strftime('%d %b %Y')}")
    rs.font.size = Pt(11); rs.font.color.rgb = GREY

    # Verdict
    doc.add_paragraph()
    vh = doc.add_paragraph()
    vr = vh.add_run("Verdict")
    vr.bold = True; vr.font.size = Pt(14); vr.font.color.rgb = BRAND
    vp = doc.add_paragraph(verdict_text)
    vp.runs[0].font.size = Pt(11)

    if misalignment:
        wp = doc.add_paragraph()
        wr = wp.add_run("⚠ COMPETITOR MIS-ALIGNMENT DETECTED")
        wr.bold = True; wr.font.color.rgb = RED; wr.font.size = Pt(12)
        doc.add_paragraph(misalignment).runs[0].font.size = Pt(10)

    # Traffic comparison
    th = doc.add_paragraph()
    tr_run = th.add_run("Traffic Comparison")
    tr_run.bold = True; tr_run.font.size = Pt(14); tr_run.font.color.rgb = BRAND
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "Site"; hdr[1].text = "Role"; hdr[2].text = "Non-brand traffic"; hdr[3].text = "Gap"
    row = table.add_row().cells
    row[0].text = client_name; row[1].text = "★ CLIENT"
    row[2].text = f"{client_traffic:,}"; row[3].text = "—"
    for cname, ctraf in sorted(comps, key=lambda x: -x[1]):
        row = table.add_row().cells
        row[0].text = cname; row[1].text = "Competitor"
        row[2].text = f"{ctraf:,}"
        row[3].text = f"{ctraf / client_traffic:.1f}x" if client_traffic else "—"

    if achievable_top10 > 0:
        ap = doc.add_paragraph()
        ar = ap.add_run(
            f"\n🎯 Realistic 6-12 month target: ~{achievable_top10:,} clicks/month "
            f"from top 10 in-scope gap keywords (see Big Wins below)."
        )
        ar.bold = True; ar.font.color.rgb = GREEN; ar.font.size = Pt(11)

    # Big Wins
    doc.add_paragraph()
    wh = doc.add_paragraph()
    wr2 = wh.add_run("🏆 Top Big-Win Opportunities")
    wr2.bold = True; wr2.font.size = Pt(14); wr2.font.color.rgb = BRAND
    for i, w in enumerate(wins, 1):
        p = doc.add_paragraph()
        run = p.add_run(f"#{i}  {w['keyword']}")
        run.bold = True; run.font.size = Pt(13); run.font.color.rgb = DARK
        sp = doc.add_paragraph()
        sr = sp.add_run(f"Volume: {w['volume']:,}/mo  ·  "
                         f"{w['best_competitor']} captures {w['competitor_traffic']:,} clicks/mo  ·  "
                         f"Client rank: {w['client_rank']}")
        sr.font.size = Pt(10); sr.font.color.rgb = GREY
        pp = doc.add_paragraph()
        pp.paragraph_format.left_indent = Cm(0.5)
        pr = pp.add_run(f"💡  {w['pitch']}")
        pr.italic = True; pr.font.size = Pt(10)

    # Top in-scope keywords table
    doc.add_paragraph()
    kh = doc.add_paragraph()
    kr = kh.add_run("Top In-Scope Gap Keywords (sorted by competitor traffic)")
    kr.bold = True; kr.font.size = Pt(14); kr.font.color.rgb = BRAND
    kt = doc.add_table(rows=1, cols=5)
    kt.style = "Light Grid Accent 1"
    hdr = kt.rows[0].cells
    hdr[0].text = "Keyword"; hdr[1].text = "Vol"; hdr[2].text = "Comp"
    hdr[3].text = "Comp rank"; hdr[4].text = "Comp traffic"
    for k in sorted(gap_kws, key=lambda x: -x["competitor_traffic"])[:15]:
        row = kt.add_row().cells
        row[0].text = k["keyword"][:40]
        row[1].text = f"{k['volume']:,}"
        row[2].text = k["best_competitor"]
        row[3].text = str(k["competitor_rank"])
        row[4].text = f"{k['competitor_traffic']:,}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


# ── Misalignment detector ───────────────────────────────────────────────────

def detect_misalignment(client_traffic: int, comps_filtered_dfs: list[pd.DataFrame],
                        comps_total_traffic: int, in_scope_kws: set[str] | None,
                        gap_kw_count: int) -> str:
    if not in_scope_kws or not comps_total_traffic:
        return ""
    in_scope_lower = {k.lower() for k in in_scope_kws}
    relevant_traffic = 0
    for cnb in comps_filtered_dfs:
        if "Current organic traffic" in cnb.columns:
            mask = cnb["Keyword"].astype(str).str.lower().isin(in_scope_lower)
            relevant_traffic += int(cnb[mask]["Current organic traffic"].sum())
    coverage_pct = (relevant_traffic / comps_total_traffic) * 100
    if coverage_pct < 10 or gap_kw_count < 5:
        return (f"Only {coverage_pct:.0f}% of competitor traffic is in the client's catalog scope, "
                f"and {gap_kw_count} keywords passed the relevance filter. The chosen competitors "
                f"may be in a different sub-category. Re-run /seo-find-competitors and pick "
                f"category-aligned peers before sharing this report.")
    return ""


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--client-name",   required=True)
    p.add_argument("--client-url",    required=True)
    p.add_argument("--client-csv",    required=True)
    p.add_argument("--competitor",    action="append", default=[],
                   help="NAME:CSV_PATH (repeatable, 1-4 times)")
    p.add_argument("--business-model", default="b2c_ecommerce")
    p.add_argument("--niche",         default="General")
    p.add_argument("--output-dir",    default="/tmp")
    p.add_argument("--in-scope-keywords", default=None,
                   help="Optional JSON list of keywords Claude marked in-scope (final pass)")
    p.add_argument("--finalize",      action="store_true",
                   help="With --in-scope-keywords, generate the final DOCX report")
    args = p.parse_args()

    # Parse competitors
    competitors = []
    for spec in args.competitor:
        parts = spec.split(":", 1)
        if len(parts) != 2:
            print(f"Bad --competitor spec: {spec}", file=sys.stderr); return 1
        competitors.append((parts[0].strip(), parts[1].strip()))

    print(f"[gap] Loading {args.client_name}...", file=sys.stderr)
    client_df = load_keywords(args.client_csv)
    client_nb = client_df[client_df["Branded"] == False].copy()
    client_traffic = int(client_nb["Current organic traffic"].sum())

    print(f"[gap] Loading {len(competitors)} competitor(s)...", file=sys.stderr)
    comp_data = []
    for name, csv_path in competitors:
        df = load_keywords(csv_path)
        nb = df[df["Branded"] == False].copy()
        comp_data.append((name, nb, int(nb["Current organic traffic"].sum())))

    # Apply intent + URL filter to all
    client_filt = _filter_intent_and_urls(client_nb, args.business_model)
    comps_filt = [(name, _filter_intent_and_urls(nb, args.business_model)) for name, nb, _ in comp_data]

    # Apply Claude's in-scope keyword filter if provided
    in_scope_set: set[str] = set()
    if args.in_scope_keywords:
        in_scope_data = json.loads(Path(args.in_scope_keywords).read_text())
        if isinstance(in_scope_data, list):
            in_scope_set = {(kw if isinstance(kw, str) else kw.get("keyword", "")).lower()
                            for kw in in_scope_data}
        elif isinstance(in_scope_data, dict) and "in_scope" in in_scope_data:
            in_scope_set = {k.lower() for k in in_scope_data["in_scope"]}

    if in_scope_set:
        comps_filt = [(name, nb[nb["Keyword"].astype(str).str.lower().isin(in_scope_set)])
                      for name, nb in comps_filt]

    print(f"[gap] Computing gap keywords...", file=sys.stderr)
    gap_kws = compute_gap_keywords(client_filt, comps_filt)
    wins = big_wins(gap_kws)

    # Achievable target — top 10 by score
    top10 = sorted(gap_kws, key=_score_big_win, reverse=True)[:10]
    achievable = sum(g["competitor_traffic"] for g in top10)

    # Misalignment check
    comps_total = sum(t for _, _, t in comp_data)
    misalign = detect_misalignment(
        client_traffic, [df for _, df in comps_filt],
        comps_total, in_scope_set if in_scope_set else None,
        len(gap_kws),
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", args.client_name.lower()).strip("-")

    # Always write the JSON dump for Claude to read
    payload = {
        "client":      {"name": args.client_name, "url": args.client_url, "traffic": client_traffic},
        "competitors": [{"name": n, "traffic": t} for n, _, t in comp_data],
        "business_model":         args.business_model,
        "niche":                  args.niche,
        "candidate_keywords":     [g["keyword"] for g in gap_kws],
        "gap_keywords":           gap_kws,
        "big_wins":               wins,
        "achievable_top10_traffic": achievable,
        "competitor_misalignment":  misalign,
        "in_scope_keywords_applied": sorted(in_scope_set) if in_scope_set else None,
    }
    json_path = out_dir / f"gap-{slug}.json"
    json_path.write_text(json.dumps(payload, indent=2))
    print(f"\n[OK] Wrote {json_path}")

    # If finalising, also write the DOCX report
    if args.finalize:
        verdict_text = "(Claude should fill in the verdict prose here in chat — the DOCX uses your summary.)"
        report_path = out_dir / f"report-{slug}.docx"
        write_report(
            report_path, args.client_name, args.client_url, client_traffic,
            [(n, t) for n, _, t in comp_data],
            verdict_text, gap_kws, wins, achievable,
            misalignment=misalign, niche=args.niche,
        )
        print(f"[OK] Wrote {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
