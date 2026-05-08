"""
find-competitors orchestrator. Pulls Ahrefs candidates + client metrics + sitemap
seeds + optional homepage scans. Writes JSON for Claude (in chat) to read and
reason about — Claude does the positioning judgement, not this script.

Usage:  python3 find.py <CLIENT_URL> [--country IN] [--limit 15] [--scan] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests


_AHREFS_BASE = "https://api.ahrefs.com/v3"

_LOC_TO_COUNTRY = {
    "india": "in", "us": "us", "uk": "uk", "united states": "us",
    "united kingdom": "uk", "australia": "au", "canada": "ca",
}
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; growisto-seo-plugin/0.1)"}

_MARKETPLACES = {
    "amazon.com", "amazon.in", "amazon.co.uk", "ebay.com", "flipkart.com",
    "myntra.com", "ajio.com", "tatacliq.com", "jiomart.com", "indiamart.com",
    "etsy.com", "walmart.com", "target.com", "aliexpress.com", "alibaba.com",
}
_RETAILERS = {
    "croma.com", "reliancedigital.in", "vijaysales.com", "lifestylestores.com",
    "shoppersstop.com", "fabindia.com", "biba.in", "globaldesi.in",
    "bestbuy.com", "newegg.com", "homedepot.com", "macys.com", "kohls.com",
    "mdcomputers.in", "elitehubs.com", "computechstore.in", "pcstudio.in",
    "myitworld.com", "sclgaming.in", "primeabgb.com",
}
_REFERENCE = {
    "wikipedia.org", "wikihow.com", "rtings.com", "wirecutter.com",
    "tomsguide.com", "techradar.com", "cnet.com", "pcmag.com",
    "reddit.com", "quora.com", "trustpilot.com", "g2.com", "capterra.com",
    "youtube.com", "indeed.com", "glassdoor.com",
}


def _load_dotenv() -> None:
    here = Path(__file__).resolve()
    for parent in [here.parents[2], here.parents[3], here.parents[4]]:
        env = parent / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return


def _classify(domain: str) -> str:
    d = domain.lower().replace("www.", "")
    parts = d.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in _MARKETPLACES: return "marketplace"
        if suffix in _RETAILERS:    return "retailer"
        if suffix in _REFERENCE:    return "reference"
    return "brand"


def _normalise(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").strip("/").lower().replace("www.", "")


def _ahrefs_competitors(target: str, country: str, limit: int, token: str) -> dict:
    params = {
        "select":   "competitor_domain,keywords_common,keywords_competitor,domain_rating,traffic",
        "target":   target,
        "country":  country,
        "date":     date.today().isoformat(),
        "mode":     "subdomains",
        "limit":    limit,
        "order_by": "keywords_common:desc",
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    r = requests.get(f"{_AHREFS_BASE}/site-explorer/organic-competitors",
                     params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    return {
        "competitors": data.get("competitors", []),
        "units_cost":  data.get("apiUsageCosts", {}).get("units-cost-total-actual", 0),
    }


def _ahrefs_metrics(target: str, country: str, token: str) -> dict:
    params = {
        "target":  target,
        "country": country,
        "date":    date.today().isoformat(),
        "mode":    "subdomains",
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    r = requests.get(f"{_AHREFS_BASE}/site-explorer/metrics",
                     params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    m = data.get("metrics", {})
    return {
        "traffic":        m.get("org_traffic", 0),
        "keywords_total": m.get("org_keywords", 0),
        "units_cost":     data.get("apiUsageCosts", {}).get("units-cost-total-actual", 0),
    }


_META_DESC_RE  = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', re.I)
_TITLE_RE      = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H2_RE         = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)
_TAG_STRIP_RE  = re.compile(r"<[^>]+>")


def _scan(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        html = r.text[:50000]
        title = (_TITLE_RE.search(html) or [None, ""])[1].strip()
        meta_match = _META_DESC_RE.search(html)
        meta = meta_match.group(1).strip() if meta_match else ""
        h2_raw = _H2_RE.findall(html)[:6]
        h2s = [_TAG_STRIP_RE.sub("", h).strip()[:80] for h in h2_raw if h.strip()]
        return {"title": title[:140], "meta": meta[:200], "h2_samples": h2s}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:80]}"}


def _seeds(url: str) -> list[str]:
    parsed = urlparse(url if "://" in url else "https://" + url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    skip = {"blog", "about", "contact", "shop", "products", "media", "cart", "account"}
    for sm in ["/sitemap.xml", "/sitemap_index.xml"]:
        try:
            r = requests.get(base + sm, headers=_HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            urls = re.findall(r"<loc>([^<]+)</loc>", r.text)[:200]
            paths = [urlparse(u).path.strip("/").split("/")[0] for u in urls]
            common = [p for p, n in Counter(paths).most_common(15)
                      if p and n >= 3 and p not in skip]
            if common:
                return common[:8]
        except Exception:
            continue
    return []


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch competitor candidates for Claude to reason about.")
    p.add_argument("client_url", help="Client URL — e.g. https://locobuzz.com/")
    p.add_argument("--country", default="in", help="Country code (in/us/uk/...)")
    p.add_argument("--limit",   type=int, default=15, help="Ahrefs candidate count")
    p.add_argument("--scan",    action="store_true", help="Also scan client + competitor homepages")
    p.add_argument("--output",  default=None, help="Output JSON path")
    args = p.parse_args()

    _load_dotenv()
    token = os.environ.get("AHREFS_API_TOKEN", "").strip()
    if not token:
        print(json.dumps({"error": "AHREFS_API_TOKEN not set in env or .env"}))
        return 1

    target = _normalise(args.client_url)
    country = _LOC_TO_COUNTRY.get(args.country.lower(), args.country.lower())

    print(f"[find] Ahrefs competitors for {target} (country={country})...", file=sys.stderr)
    comps = _ahrefs_competitors(target, country, args.limit, token)
    print(f"[find] {len(comps['competitors'])} candidates ({comps['units_cost']} units)", file=sys.stderr)

    print(f"[find] Client metrics...", file=sys.stderr)
    metrics = _ahrefs_metrics(target, country, token)

    print(f"[find] Sitemap seeds...", file=sys.stderr)
    seeds = _seeds(args.client_url)

    candidates = []
    for c in comps["competitors"]:
        d = c["competitor_domain"]
        candidates.append({
            "domain":          d,
            "type":            _classify(d),
            "keywords_common": c.get("keywords_common", 0),
            "keywords_total":  c.get("keywords_competitor", 0),
            "traffic":         c.get("traffic", 0),
            "domain_rating":   c.get("domain_rating", 0),
            "scan":            None,
        })

    client_scan = None
    if args.scan:
        print(f"[find] Scanning {len(candidates) + 1} homepages...", file=sys.stderr)
        client_scan = _scan(args.client_url)
        for c in candidates:
            c["scan"] = _scan(c["domain"])

    output = {
        "client": {
            "url":            args.client_url,
            "domain":         target,
            "country":        country,
            "traffic":        metrics["traffic"],
            "keywords_total": metrics["keywords_total"],
            "category_seeds": seeds,
            "scan":           client_scan,
        },
        "candidates":       candidates,
        "total_units_used": comps["units_cost"] + metrics["units_cost"],
    }

    out_path = args.output
    if not out_path:
        slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-")
        out_path = f"/tmp/seo-competitors-{slug}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(output, indent=2))

    print(f"\n[OK] Wrote {out_path}")
    print(f"     Total Ahrefs units used: {output['total_units_used']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
