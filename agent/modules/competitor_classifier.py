"""
Classify a competitor domain as Brand / Retailer / Marketplace / Reference / Unknown.

This solves a real problem: Ahrefs' "organic-competitors" ranks by keyword overlap,
which often surfaces multi-brand retailers (Croma, Reliance Digital) instead of
the actual brand peers (Razer, Logitech) that the analyst cares about.

Strategy:
  1. Known-domain lookup — instant classification for major retailers/marketplaces
  2. Heuristic homepage crawl — detect multi-brand signals on unknown domains
"""

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ── Known marketplaces (sell across many categories) ─────────────────────────
_MARKETPLACES = {
    "amazon.com", "amazon.in", "amazon.co.uk", "amazon.com.au", "amazon.ae",
    "ebay.com", "ebay.in", "ebay.co.uk",
    "flipkart.com", "myntra.com", "ajio.com", "meesho.com", "snapdeal.com",
    "tatacliq.com", "jiomart.com", "indiamart.com", "tradeindia.com",
    "shopclues.com", "nykaa.com", "purplle.com",
    "walmart.com", "target.com", "costco.com",
    "etsy.com", "wayfair.com", "aliexpress.com", "alibaba.com",
}

# ── Known multi-brand retailers (sell others' brands) ────────────────────────
_RETAILERS = {
    # India electronics/PC retailers
    "croma.com", "reliancedigital.in", "vijaysales.com",
    "mdcomputers.in", "computechstore.in", "pcstudio.in", "elitehubs.com",
    "sclgaming.in", "myitworld.com", "primeabgb.com", "techbar.in",
    "theitdepot.com", "smcinternational.in",
    # India fashion retailers
    "lifestylestores.com", "shoppersstop.com", "max.in", "westside.com",
    "fabindia.com", "globaldesi.in", "biba.in",
    # India general retailers
    "bigbasket.com", "blinkit.com", "swiggy.com", "zomato.com",
    # US/global retailers
    "bestbuy.com", "newegg.com", "bhphotovideo.com", "homedepot.com",
    "lowes.com", "macys.com", "kohls.com", "nordstrom.com",
    "currys.co.uk", "argos.co.uk", "very.co.uk",
}

# ── Known reference / review / wiki / news ──────────────────────────────────
_REFERENCE = {
    "wikipedia.org", "en.wikipedia.org", "wikihow.com", "britannica.com",
    "rtings.com", "consumerreports.org", "wirecutter.com", "tomsguide.com",
    "tomshardware.com", "techradar.com", "cnet.com", "pcmag.com",
    "thespruce.com", "goodhousekeeping.com", "bhg.com",
    "reddit.com", "quora.com", "stackoverflow.com",
    "tripadvisor.com", "yelp.com", "trustpilot.com", "g2.com", "capterra.com",
    "indeed.com", "glassdoor.com",
    "nytimes.com", "bbc.com", "cnn.com", "forbes.com", "economist.com",
    "youtube.com", "tiktok.com",
    "dictionary.com", "thesaurus.com", "vocabulary.com",
}

# ── Multi-brand UI hints in homepage HTML ───────────────────────────────────
_MULTIBRAND_PATTERNS = [
    re.compile(r"\bshop by brand\b", re.I),
    re.compile(r"\bbrowse brands\b", re.I),
    re.compile(r"\b(?:our |all |featured )?brands\s*(?:we sell|offered|available)\b", re.I),
    re.compile(r"\b(?:multi-?brand|multiple brands)\b", re.I),
    re.compile(r"\bauthorized (?:retailer|reseller|dealer)\b", re.I),
]


def _domain_root(url_or_domain: str) -> str:
    s = url_or_domain.replace("https://", "").replace("http://", "")
    s = s.strip("/").split("/")[0]
    return s.replace("www.", "").lower()


def _classify_known(domain: str) -> str | None:
    if domain in _MARKETPLACES: return "marketplace"
    if domain in _RETAILERS:    return "retailer"
    if domain in _REFERENCE:    return "reference"
    # Subdomain match: en.wikipedia.org → wikipedia.org
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in _MARKETPLACES: return "marketplace"
        if suffix in _RETAILERS:    return "retailer"
        if suffix in _REFERENCE:    return "reference"
    return None


def _classify_via_crawl(domain: str, timeout: int = 10) -> str:
    """Crawl homepage; detect multi-brand patterns. Returns brand|retailer|unknown."""
    url = f"https://{domain}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return "unknown"
    except requests.RequestException:
        return "unknown"

    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text(" ", strip=True).lower()

    # Strong retailer signal: explicit multi-brand UI
    for pat in _MULTIBRAND_PATTERNS:
        if pat.search(text):
            return "retailer"

    # /brands/ or /brand/ in nav links
    nav_hrefs = " ".join(a.get("href", "") for a in soup.find_all("a", href=True)[:120]).lower()
    if re.search(r"/brands?/", nav_hrefs):
        return "retailer"

    # Count known brand mentions on the page (HyperX, Razer, Logitech, Samsung, Apple, etc.)
    common_brands = [
        "razer", "logitech", "corsair", "steelseries", "hyperx", "asus", "msi",
        "lenovo", "dell", "hp", "acer", "samsung", "apple", "sony", "lg",
        "nike", "adidas", "puma", "reebok", "levi", "tommy hilfiger",
        "philips", "bosch", "panasonic", "whirlpool", "lg", "godrej",
    ]
    brand_hits = sum(1 for b in common_brands if re.search(rf"\b{re.escape(b)}\b", text))
    if brand_hits >= 5:
        return "retailer"   # selling 5+ different big brands is a clear retailer signal

    return "brand"   # default — single-brand site


def classify(domain: str, *, deep: bool = True) -> str:
    """
    Returns one of: 'brand' | 'retailer' | 'marketplace' | 'reference' | 'unknown'.

    `deep=False` returns 'unknown' for non-cataloged domains (no crawl).
    `deep=True` crawls unknowns to detect multi-brand signals.
    """
    domain = _domain_root(domain)
    known = _classify_known(domain)
    if known: return known
    if not deep: return "unknown"
    return _classify_via_crawl(domain)


# Display helpers ─────────────────────────────────────────────────────────────
TYPE_BADGE = {
    "brand":       "🏢 Brand",
    "retailer":    "🛒 Retailer",
    "marketplace": "🛍️ Marketplace",
    "reference":   "📰 Reference",
    "unknown":     "❓ Unknown",
}

# Sort priority — analysts usually want brands first
TYPE_PRIORITY = {
    "brand":       0,
    "unknown":     1,
    "retailer":    2,
    "marketplace": 3,
    "reference":   4,
}


if __name__ == "__main__":
    import sys, json
    domains = sys.argv[1:] or [
        "razer.com", "logitech.com", "hp.com",
        "croma.com", "amazon.in", "rtings.com",
        "mdcomputers.in", "vinodcookware.com",
    ]
    for d in domains:
        print(f"  {d:30s} → {TYPE_BADGE.get(classify(d, deep=True), '?')}")
