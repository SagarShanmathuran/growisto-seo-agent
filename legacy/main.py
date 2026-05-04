#!/usr/bin/env python3
"""
SEO Potential Analysis — CLI
No API keys required. Pure Python.

Usage:
  python main.py example.com competitor.com
  python main.py -f domains.txt
  python main.py example.com -o report.json --verbose
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from src.analyzer import SEOAnalyzer, SiteResult

# ── report formatting ─────────────────────────────────────────────────────────

_ICON  = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "❄️"}
_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _bar(score: float, width: int = 20) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def print_report(results: list[SiteResult]) -> None:
    valid  = [r for r in results if r.error is None]
    errors = [r for r in results if r.error is not None]

    sorted_r = sorted(
        valid,
        key=lambda x: (_ORDER.get(x.potential_level, 3), -x.potential_score),
    )

    W = 62
    print("\n" + "=" * W)
    print("  SEO POTENTIAL ANALYSIS REPORT")
    print(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M')}  |  {len(valid)} site(s)")
    print("=" * W)

    for level in ("HIGH", "MEDIUM", "LOW"):
        group = [r for r in sorted_r if r.potential_level == level]
        if not group:
            continue
        print(f"\n{_ICON[level]}  {level} POTENTIAL  ({len(group)})")
        print("-" * W)

        for r in group:
            sig = r.key_signals
            outreach = "✅ Reach out" if r.recommend_outreach else "❌ Skip"

            print(f"\n  {r.domain}")
            print(f"  SEO Health    {_bar(r.health_score)}  {r.health_score:.0f}/100")
            print(f"  Opportunity   {_bar(r.potential_score)}  {r.potential_score:.0f}/100")
            print(f"  Outreach      {outreach}")
            print(f"  Checks failed {sig.get('checks_failed', '?')} / passed {sig.get('checks_passed', '?')}")

            # key signals at a glance
            flags = []
            if not sig.get("uses_https"):        flags.append("⚠ No HTTPS")
            if sig.get("load_time_s", 0) >= 3:   flags.append(f"⚠ Slow ({sig['load_time_s']}s)")
            if not sig.get("meta_desc_len"):      flags.append("⚠ No meta desc")
            if sig.get("h1_count", 0) != 1:      flags.append(f"⚠ H1×{sig.get('h1_count',0)}")
            if not sig.get("has_sitemap"):        flags.append("⚠ No sitemap")
            if not sig.get("has_schema"):         flags.append("⚠ No schema")
            if sig.get("img_no_alt", 0) > 0:     flags.append(f"⚠ {sig['img_no_alt']} imgs no alt")
            if flags:
                print("  Issues:  " + "  ".join(flags))

            # top recommendations
            if r.recommendations:
                print("  Top fixes:")
                for rec in r.recommendations[:3]:
                    p = rec["priority"]
                    print(f"    [{p}] {rec['recommendation']}")

    if errors:
        print(f"\n⚠️  ERRORS ({len(errors)})")
        for r in errors:
            print(f"  {r.domain}  —  {r.error}")

    outreach_count = sum(1 for r in valid if r.recommend_outreach)
    print(f"\n{'=' * W}")
    print(f"  SUMMARY: {outreach_count} / {len(valid)} sites recommended for outreach")
    print("=" * W)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyse websites for SEO outreach potential — pure Python, no API keys.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py example.com
  python main.py site1.com site2.com site3.com
  python main.py -f domains.txt -o results.json
  python main.py example.com --verbose
        """,
    )
    p.add_argument("domains", nargs="*", help="Domains to analyse")
    p.add_argument("-f", "--file",    metavar="PATH", help="Text file, one domain per line")
    p.add_argument("-o", "--output",  metavar="PATH", help="Save JSON results to file")
    p.add_argument("-v", "--verbose", action="store_true", help="Show scores during analysis")
    return p.parse_args()


def _collect_domains(args: argparse.Namespace) -> list[str]:
    domains = list(args.domains)
    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    domains.append(line)
    return domains


def main() -> None:
    args    = _parse_args()
    domains = _collect_domains(args)

    if not domains:
        print("No domains supplied — run with --help for usage.")
        sys.exit(1)

    print(f"\nSEO Potential Analyzer  |  {len(domains)} site(s)\n")

    analyzer = SEOAnalyzer()
    results  = analyzer.analyze_batch(domains, verbose=args.verbose)

    print_report(results)

    out = args.output or f"seo_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in results], fh, indent=2, ensure_ascii=False)
    print(f"\n💾  Full JSON saved → {out}\n")


if __name__ == "__main__":
    main()
