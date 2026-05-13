"""
find-competitors orchestrator. Three-signal merge:
  1. Ahrefs organic-competitors (keyword overlap)
  2. SearchAPI Google SERPs (live co-occurrence on client's top product keywords)
  3. (LLM peer-brand discovery happens in chat, not here)

Candidates appearing in >=2 signals get high_confidence=true. Single-source
picks are flagged for analyst review. Claude (in chat) applies positioning
judgement — this script just gathers data.

Usage:  python3 find.py <CLIENT_URL> [--country IN] [--limit 15] [--scan]
                       [--no-serp] [--output PATH]
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


# ── SerpAPI / SearchAPI cross-check ──────────────────────────────────────────

_SERP_ENDPOINT = "https://www.searchapi.io/api/v1/search"

# Domains that show up in SERPs but aren't real business competitors
_SERP_BLOCKLIST = {
    "amazon.com", "amazon.in", "amazon.co.uk", "ebay.com", "flipkart.com",
    "myntra.com", "ajio.com", "tatacliq.com", "jiomart.com", "indiamart.com",
    "meesho.com", "snapdeal.com", "nykaa.com", "etsy.com", "walmart.com",
    "wikipedia.org", "wikihow.com", "reddit.com", "quora.com", "youtube.com",
    "facebook.com", "instagram.com", "twitter.com", "linkedin.com", "pinterest.com",
    "google.com", "google.co.in", "bing.com",
    "trustpilot.com", "g2.com", "capterra.com", "glassdoor.com", "indeed.com",
    "healthline.com", "webmd.com", "medanta.org", "parashospitals.com",
    "metropolisindia.com", "apollohospitals.com", "1mg.com", "netmeds.com",
    "ndtv.com", "hindustantimes.com", "timesofindia.com", "thehindu.com",
    "tomsguide.com", "techradar.com", "cnet.com", "pcmag.com", "rtings.com",
    "shopify.com", "wix.com", "wordpress.com",
}
_SERP_BLOCK_KEYWORDS = ("wiki", "blog", "news", "review", "forum", "magazine",
                       "compare", "guide", "tutorial", "encyclopedia")


def _is_real_competitor(domain: str) -> bool:
    d = domain.lower().replace("www.", "").strip()
    if not d:
        return False
    if d in _SERP_BLOCKLIST:
        return False
    parts = d.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in _SERP_BLOCKLIST:
            return False
    root = parts[0]
    for kw in _SERP_BLOCK_KEYWORDS:
        if kw in root:
            return False
    return True


def _serp_competitors(seed_keywords: list[str], country: str, api_key: str,
                      client_domain: str, max_keywords: int = 5
                      ) -> tuple[list[dict], int, list[str]]:
    """
    For each seed keyword, fetch Google SERP via SearchAPI. Collect domains
    that appear across multiple SERPs. Returns (competitors, calls_made, errors).
    """
    _GEO = {
        "in": {"google_domain": "google.co.in", "gl": "in", "hl": "en", "location": "India"},
        "us": {"google_domain": "google.com",   "gl": "us", "hl": "en", "location": "United States"},
        "uk": {"google_domain": "google.co.uk", "gl": "uk", "hl": "en", "location": "United Kingdom"},
        "au": {"google_domain": "google.com.au","gl": "au", "hl": "en", "location": "Australia"},
        "ca": {"google_domain": "google.ca",    "gl": "ca", "hl": "en", "location": "Canada"},
    }
    geo = _GEO.get(country.lower(), _GEO["in"])

    domain_hits: dict[str, list[tuple[str, int]]] = {}
    errors: list[str] = []
    calls = 0
    client_root = client_domain.lower().replace("www.", "").split(".")[0]

    for kw in seed_keywords[:max_keywords]:
        params = {
            "engine":   "google",
            "q":        kw,
            "api_key":  api_key,
            **geo,
        }
        try:
            r = requests.get(_SERP_ENDPOINT, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            calls += 1
            if "error" in data:
                errors.append(f"{kw}: {data['error']}")
                continue
            for result in data.get("organic_results", [])[:10]:
                d = result.get("domain", "").replace("www.", "").lower().strip()
                if not d or client_root in d or not _is_real_competitor(d):
                    continue
                pos = int(result.get("position", 99))
                domain_hits.setdefault(d, []).append((kw, pos))
        except Exception as e:
            errors.append(f"{kw}: {type(e).__name__}: {str(e)[:80]}")

    out = []
    for domain, hits in domain_hits.items():
        positions = [p for _, p in hits]
        out.append({
            "domain":            domain,
            "serp_frequency":    len(hits),
            "serp_avg_position": round(sum(positions) / len(positions), 1),
            "serp_best_position": min(positions),
            "serp_keywords":     [k for k, _ in hits],
        })
    out.sort(key=lambda c: (-c["serp_frequency"], c["serp_avg_position"]))
    return out, calls, errors


def _build_seed_keywords(category_seeds: list[str], niche: str | None,
                         client_scan: dict | None) -> list[str]:
    """
    Build 3-5 commercial seed keywords to pass to SerpAPI.
    Combines sitemap category seeds with niche hint if available.
    """
    seeds = []
    if niche:
        for cat in category_seeds[:3]:
            seeds.append(f"{cat} {niche}".strip())
    else:
        seeds.extend(category_seeds[:5])
    # Add a buyer-intent variant of the strongest category
    if category_seeds and niche:
        seeds.append(f"best {category_seeds[0]} {niche}".strip())
    elif category_seeds:
        seeds.append(f"buy {category_seeds[0]}".strip())
    # De-dupe while preserving order
    seen = set()
    out = []
    for s in seeds:
        s = s.lower().strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:5]


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch competitor candidates for Claude to reason about.")
    p.add_argument("client_url", help="Client URL — e.g. https://locobuzz.com/")
    p.add_argument("--country", default="in", help="Country code (in/us/uk/...)")
    p.add_argument("--limit",   type=int, default=15, help="Ahrefs candidate count")
    p.add_argument("--scan",    action="store_true", help="Also scan client + competitor homepages")
    p.add_argument("--niche",   default=None,
                   help="One-line niche hint (helps SerpAPI seed kws). e.g. 'dry fruits and nuts D2C'")
    p.add_argument("--no-serp", action="store_true",
                   help="Skip SerpAPI cross-check even if SEARCHAPI_KEY is set")
    p.add_argument("--serp-keywords", type=int, default=5,
                   help="Number of seed keywords to fetch SERPs for (default 5)")
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

    # Build Ahrefs candidate map keyed by domain (lowercased, www-stripped)
    candidates_by_domain: dict[str, dict] = {}
    for c in comps["competitors"]:
        d_raw = c["competitor_domain"]
        d_key = d_raw.lower().replace("www.", "").strip()
        candidates_by_domain[d_key] = {
            "domain":          d_raw,
            "type":            _classify(d_raw),
            "keywords_common": c.get("keywords_common", 0),
            "keywords_total":  c.get("keywords_competitor", 0),
            "traffic":         c.get("traffic", 0),
            "domain_rating":   c.get("domain_rating", 0),
            "scan":            None,
            "sources":         ["ahrefs"],
            "ahrefs_rank":     None,
            "serp_data":       None,
        }

    # Optional client scan (used for seed building + reported in output)
    client_scan = None
    if args.scan:
        client_scan = _scan(args.client_url)

    # ── SerpAPI cross-check ──────────────────────────────────────────────────
    serp_key = os.environ.get("SEARCHAPI_KEY", "").strip()
    serp_meta: dict = {"used": False, "calls": 0, "errors": [], "seed_keywords": []}

    if not args.no_serp and serp_key and seeds:
        seed_kws = _build_seed_keywords(seeds, args.niche, client_scan)
        print(f"[find] SerpAPI cross-check on {len(seed_kws)} seed kws: {seed_kws}", file=sys.stderr)
        serp_results, calls, errors = _serp_competitors(
            seed_kws, country, serp_key, target, max_keywords=args.serp_keywords)
        serp_meta = {
            "used": True, "calls": calls, "errors": errors,
            "seed_keywords": seed_kws,
        }
        # Merge SERP results into candidates_by_domain
        for sr in serp_results:
            d_key = sr["domain"]
            if d_key in candidates_by_domain:
                # Existing Ahrefs candidate — add serp source + data
                candidates_by_domain[d_key]["sources"].append("serp")
                candidates_by_domain[d_key]["serp_data"] = {
                    "frequency":     sr["serp_frequency"],
                    "avg_position":  sr["serp_avg_position"],
                    "best_position": sr["serp_best_position"],
                    "keywords":      sr["serp_keywords"],
                }
            else:
                # New SERP-only candidate — Ahrefs missed it
                candidates_by_domain[d_key] = {
                    "domain":          sr["domain"],
                    "type":            _classify(sr["domain"]),
                    "keywords_common": 0,
                    "keywords_total":  0,
                    "traffic":         0,
                    "domain_rating":   0,
                    "scan":            None,
                    "sources":         ["serp"],
                    "ahrefs_rank":     None,
                    "serp_data": {
                        "frequency":     sr["serp_frequency"],
                        "avg_position":  sr["serp_avg_position"],
                        "best_position": sr["serp_best_position"],
                        "keywords":      sr["serp_keywords"],
                    },
                }
        print(f"[find] SerpAPI added {sum(1 for c in candidates_by_domain.values() if 'serp' in c['sources'] and 'ahrefs' not in c['sources'])} new candidates "
              f"and cross-confirmed {sum(1 for c in candidates_by_domain.values() if len(c['sources']) >= 2)}",
              file=sys.stderr)
    elif args.no_serp:
        serp_meta["skip_reason"] = "--no-serp flag set"
    elif not serp_key:
        serp_meta["skip_reason"] = "SEARCHAPI_KEY not set"
    elif not seeds:
        serp_meta["skip_reason"] = "no sitemap seeds to build SERP queries from"

    # Mark high confidence (in ≥2 sources)
    for c in candidates_by_domain.values():
        c["high_confidence"] = len(c["sources"]) >= 2

    candidates = list(candidates_by_domain.values())
    candidates.sort(key=lambda c: (
        -1 if c["high_confidence"] else 0,
        -c["keywords_common"],
        -(c.get("serp_data") or {}).get("frequency", 0),
    ))

    # Scan candidate homepages (if requested)
    if args.scan:
        print(f"[find] Scanning {len(candidates) + 1} homepages...", file=sys.stderr)
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
        "serp_cross_check": serp_meta,
        "high_confidence_count": sum(1 for c in candidates if c["high_confidence"]),
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
    if serp_meta["used"]:
        print(f"     SerpAPI calls: {serp_meta['calls']}")
        print(f"     High-confidence picks (>=2 sources): {output['high_confidence_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
