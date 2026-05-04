#!/usr/bin/env python3
"""
SEO Potential Analysis — CLI Orchestrator

Workflow:
  1. Take client URL + manual paths to client/competitor Ahrefs CSVs
  2. Detect business model (B2C/B2B/financial)
  3. Crawl client site for on-page health check
  4. Compute gap analysis vs competitors
  5. Compute ROI (calibrated to ₹1.5L/mo retainer)
  6. Synthesize H/M/L verdict (Gemini Flash w/ template fallback)
  7. Generate Word report (Growisto branded)

Usage:
  python analyze.py --client-url vinodcookware.com \
    --client-name "Vinod Cookware" \
    --client-keywords path/to/vinod_keywords.csv \
    --client-pages    path/to/vinod_pages.csv \
    --competitor "Milton:path/to/milton_kw.csv:path/to/milton_pages.csv" \
    --competitor "Borosil:path/to/borosil_kw.csv:path/to/borosil_pages.csv" \
    --niche Cookware --location India --aov 1800
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from agent.modules.ahrefs_csv_loader import load as load_site
from agent.modules.gap_analyzer import analyze as analyze_gap
from agent.modules.report_data_builder import (
    build_ahrefs_dict, build_comp_traffic_dict
)
from agent.modules.business_model_detector import detect as detect_model
from agent.services.roi_calculator import calculate_roi, calculate_roi_scenarios
from agent.services.gemini_client import synthesize_verdict
from agent.services.word_report import generate_word_report
from agent.seo_core.analyzer import SEOAnalyzer


def _parse_competitor(spec: str) -> tuple[str, str, str | None]:
    """
    Accepts either:
        NAME:keywords.csv               (preferred — page data derived from keywords)
        NAME:keywords.csv:pages.csv     (legacy — explicit pages file)
    """
    parts = spec.split(":")
    if len(parts) < 2:
        raise ValueError(f"Bad competitor spec '{spec}'. Expected NAME:keywords.csv[:pages.csv]")
    name = parts[0]
    if len(parts) == 2:
        return name, parts[1], None
    kw = ":".join(parts[1:-1]) if len(parts) > 3 else parts[1]
    pg = parts[-1]
    return name, kw, pg


def main():
    ap = argparse.ArgumentParser(description="SEO Potential Analysis (CSV-based, no APIs required)")
    ap.add_argument("--client-url",      required=True)
    ap.add_argument("--client-name",     required=True)
    ap.add_argument("--client-keywords", required=True, help="Ahrefs keywords CSV for client")
    ap.add_argument("--client-pages",    default=None, help="(Optional) Ahrefs top-pages CSV — derived from keywords if omitted")
    ap.add_argument("--competitor",      action="append", default=[],
                    help="NAME:keywords.csv[:pages.csv] — pages CSV optional (repeatable)")
    ap.add_argument("--niche",           default="General")
    ap.add_argument("--location",        default="India")
    ap.add_argument("--currency",        default="₹")
    ap.add_argument("--aov",             type=float, default=2000,
                    help="Average order value or contract value (in --currency units)")
    ap.add_argument("--seo-cost",        type=float, default=150_000,
                    help="Monthly SEO retainer cost (default ₹1.5L)")
    ap.add_argument("--cvr",             type=float, default=0.02, help="Conversion rate")
    ap.add_argument("--skip-crawl",      action="store_true", help="Skip on-page health crawl")
    ap.add_argument("-o", "--output",    help="Output DOCX path")
    args = ap.parse_args()

    print(f"\n🔍  SEO Potential Analysis — {args.client_name}")
    print("─" * 60)

    # 1. Load client + competitor data
    print("📊  Loading Ahrefs CSVs...")
    client = load_site(args.client_name, args.client_keywords, args.client_pages)
    print(f"   Client: {client.nb_traffic:,} non-brand traffic, {client.page_count} pages, {client.top10_count} top-10 keywords")

    competitors = []
    for spec in args.competitor:
        name, kw, pg = _parse_competitor(spec)
        c = load_site(name, kw, pg)
        competitors.append(c)
        print(f"   {name}: {c.nb_traffic:,} traffic, {c.page_count} pages")

    if not competitors:
        print("⚠ No competitors specified — analysis will be limited.", file=sys.stderr)

    # 2. Business model detection
    print("\n🏷️  Detecting business model...")
    bm = detect_model(args.client_url)
    print(f"   Type: {bm.primary} (confidence {bm.confidence:.2f})")

    # 3. On-page crawl
    site_result = None
    if not args.skip_crawl:
        print("\n🌐  Crawling client site for on-page health check...")
        try:
            site_result = SEOAnalyzer().analyze(args.client_url)
            print(f"   Health: {site_result.health_score:.0f}/100, "
                  f"{len(site_result.recommendations)} on-page issues found")
        except Exception as e:
            print(f"   ⚠ Crawl failed: {e}")

    # 4. Gap analysis
    print("\n🔎  Computing gap analysis...")
    gap = analyze_gap(client, competitors)
    print(f"   Traffic ratio: {gap.traffic_ratio:.2f} | Gap keywords: {len(gap.gap_keywords)} ({gap.gap_total_volume:,} vol)")
    for note in gap.notes:
        print(f"   • {note}")

    # 5. ROI
    print("\n💰  Computing ROI...")
    avg_comp_traffic = int(sum(c.nb_traffic for c in competitors) / len(competitors)) if competitors else 0
    total_comp_traffic = sum(c.nb_traffic for c in competitors)
    # Incremental-traffic ROI: target = avg competitor traffic
    roi = calculate_roi(
        client_current_traffic=client.nb_traffic,
        target_traffic=avg_comp_traffic,
        aov=args.aov,
        conversion_rate=args.cvr,
        monthly_seo_cost=args.seo_cost,
    )
    roi_scenarios = calculate_roi_scenarios(
        client.nb_traffic, [c.nb_traffic for c in competitors],
        aov=args.aov, conversion_rate=args.cvr, monthly_seo_cost=args.seo_cost,
    )
    print(f"   Target {roi['target_traffic']:,}/mo (current {roi['client_current_traffic']:,}) → +{roi['incremental_traffic']:,}/mo incremental")
    print(f"   Est. revenue: {args.currency}{roi['monthly_revenue']:,.0f}/mo  →  ROI: {roi['roi_multiple']}x ({roi['viability']})")

    # 6. LLM verdict
    print("\n🧠  Synthesizing verdict...")
    verdict_input = {
        "client_name": args.client_name,
        "client_url": args.client_url,
        "niche": args.niche,
        "client_traffic": client.nb_traffic,
        "avg_comp_traffic": avg_comp_traffic,
        "traffic_ratio": gap.traffic_ratio,
        "gap_total_volume": gap.gap_total_volume,
        "top_gap_keywords": [(g.keyword, g.volume, g.best_competitor, g.competitor_rank)
                             for g in gap.gap_keywords[:10]],
        "page_count_delta": gap.page_count_delta,
        "business_model": bm.primary,
        "roi_pct": roi["roi_pct"],
        "roi_viable": roi["is_viable"],
        "notes": gap.notes,
    }
    verdict = synthesize_verdict(verdict_input, verbose=True)
    print(f"   → {verdict['potential']}: {verdict['summary'][:160]}...")

    # 7. Build report
    print("\n📄  Generating Word report...")
    ahrefs_dict = build_ahrefs_dict(client, competitors, gap)
    comp_traffic = build_comp_traffic_dict(competitors)

    docx_bytes = generate_word_report(
        client_url=args.client_url,
        niche=args.niche,
        location=args.location,
        currency_symbol=args.currency,
        ai_result=verdict,
        roi=roi,
        comp_traffic=comp_traffic,
        ahrefs=ahrefs_dict,
        site_result=site_result,
        roi_scenarios=roi_scenarios,
    )

    out = args.output or f"seo_report_{args.client_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    Path(out).write_bytes(docx_bytes)
    print(f"\n✅  Report saved: {out}")
    print(f"   {len(docx_bytes):,} bytes")


if __name__ == "__main__":
    main()
