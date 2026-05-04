"""SearchAPI.io integration — discover competitor domains from Google SERPs."""

import requests
from collections import defaultdict


_ENDPOINT = "https://www.searchapi.io/api/v1/search"

# ── domains to exclude (marketplaces, forums, editorials, social, info sites) ──

_BLOCKLIST: set[str] = {
    # Marketplaces
    "amazon.com", "amazon.co.uk", "amazon.in", "amazon.com.au", "amazon.ca",
    "amazon.de", "amazon.fr", "amazon.ae", "amazon.sg",
    "ebay.com", "ebay.co.uk", "ebay.in", "ebay.com.au",
    "flipkart.com", "walmart.com", "target.com", "etsy.com", "wayfair.com",
    "aliexpress.com", "alibaba.com", "dhgate.com", "made-in-china.com",
    "overstock.com", "homedepot.com", "lowes.com", "costco.com",
    "bestbuy.com", "newegg.com", "bhphotovideo.com",
    "meesho.com", "snapdeal.com", "myntra.com", "ajio.com", "nykaa.com",
    "tatacliq.com", "jiomart.com", "indiamart.com", "tradeindia.com",
    "shopclues.com", "pepperfry.com", "urbanladder.com",
    # Forums / Q&A / Communities
    "reddit.com", "quora.com", "stackoverflow.com", "stackexchange.com",
    "answers.com", "yahoo.com", "ask.com", "discourse.com",
    "tripadvisor.com", "yelp.com", "trustpilot.com", "g2.com", "capterra.com",
    "glassdoor.com", "indeed.com",
    # General info / encyclopaedias
    "wikipedia.org", "wikihow.com", "wikidata.org", "britannica.com",
    "dictionary.com", "merriam-webster.com",
    # News / Editorial / Blogs
    "cnn.com", "bbc.com", "bbc.co.uk", "nytimes.com", "theguardian.com",
    "forbes.com", "businessinsider.com", "inc.com", "entrepreneur.com",
    "huffpost.com", "buzzfeed.com", "vox.com", "theatlantic.com",
    "washingtonpost.com", "usatoday.com", "nbcnews.com", "abcnews.go.com",
    "foxnews.com", "reuters.com", "apnews.com", "bloomberg.com", "wsj.com",
    "ft.com", "economist.com", "ndtv.com", "hindustantimes.com",
    "timesofindia.com", "livemint.com", "thehindu.com", "moneycontrol.com",
    "techcrunch.com", "theverge.com", "wired.com", "engadget.com",
    "cnet.com", "pcmag.com", "techradar.com", "tomsguide.com", "tomshardware.com",
    "wirecutter.com", "rtings.com", "consumerreports.org",
    # Review / Comparison / Listicle
    "bestreviews.com", "reviewed.com", "goodhousekeeping.com",
    "bhg.com", "housebeautiful.com", "architecturaldigest.com",
    "thespruce.com", "realsimple.com", "marthastewart.com",
    "foodnetwork.com", "allrecipes.com", "epicurious.com", "seriouseats.com",
    "food52.com", "bonappetit.com", "tasteofhome.com",
    # Social media / Video
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "pinterest.com", "youtube.com", "tiktok.com",
    "snapchat.com", "tumblr.com", "medium.com", "substack.com",
    # Search engines / Google properties
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com",
    "google.co.in", "google.co.uk",
    # Price comparison
    "pricespy.com", "priceme.com", "shopzilla.com", "nextag.com",
    "bizrate.com", "pricegrabber.com",
    # Domain/hosting/generic tech
    "shopify.com", "wix.com", "squarespace.com", "wordpress.com",
    "godaddy.com", "bluehost.com",
}

_BLOCK_KEYWORDS = (
    "wiki", "news", "forum", "blog", "magazine", "review", "compare",
    "deals", "coupon", "promo", "discount", "price", "cheap", "free",
    "howto", "how-to", "guide", "learn", "tutorial", "tips", "advice",
    "reddit", "quora", "answers",
    # Reference / dictionary / encyclopedia
    "dictionary", "thesaurus", "vocabulary", "encyclopedia", "shabdkosh",
    "collinsdictionary", "merriam", "lexico", "wordnik", "wordreference",
    "translate", "babbel", "duolingo",
)


def _is_business_competitor(domain: str) -> bool:
    domain = domain.lower().strip()
    if domain in _BLOCKLIST:
        return False
    # Subdomain match: en.wikipedia.org → wikipedia.org → blocked
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in _BLOCKLIST:
            return False
    root = parts[0]
    for kw in _BLOCK_KEYWORDS:
        if kw in root:
            return False
    return True


def fetch_competitors(
    keywords: list[str],
    api_key: str,
    location: str = "United States",
    num_results: int = 10,
    min_frequency: int = 1,
) -> tuple[list[dict], list[str]]:
    """
    For each keyword, fetch Google organic SERP via SearchAPI.
    Returns (competitors, errors) where each competitor has:
      domain, frequency, avg_position, best_position, keywords_found_in (list)

    `min_frequency` filters out one-off appearances when ≥ 2.
    """
    kw_positions: dict[str, list[tuple[str, int]]] = defaultdict(list)
    errors: list[str] = []

    # Country-specific Google params boost geo-relevant competitor discovery
    _LOC_HINTS = {
        "india":          {"google_domain": "google.co.in", "gl": "in", "hl": "en"},
        "united kingdom": {"google_domain": "google.co.uk", "gl": "uk", "hl": "en"},
        "united states":  {"google_domain": "google.com",   "gl": "us", "hl": "en"},
        "australia":      {"google_domain": "google.com.au","gl": "au", "hl": "en"},
        "canada":         {"google_domain": "google.ca",    "gl": "ca", "hl": "en"},
        "uae":            {"google_domain": "google.ae",    "gl": "ae", "hl": "en"},
        "singapore":      {"google_domain": "google.com.sg","gl": "sg", "hl": "en"},
    }
    geo_params = _LOC_HINTS.get(location.lower().strip(), {})

    for kw in keywords:
        params = {
            "engine":   "google",
            "q":        kw,
            "location": location,
            "api_key":  api_key,
            **geo_params,
        }
        try:
            resp = requests.get(_ENDPOINT, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                errors.append(f"{kw}: {data['error']}")
                continue

            for result in data.get("organic_results", [])[:num_results]:
                domain = result.get("domain", "").replace("www.", "").lower().strip()
                pos    = int(result.get("position", 99))
                if domain and _is_business_competitor(domain):
                    kw_positions[domain].append((kw, pos))

        except requests.RequestException as exc:
            errors.append(f"{kw}: {exc}")

    # Rank by: frequency (primary) → best position (secondary)
    competitors = []
    for domain, hits in kw_positions.items():
        freq = len(hits)
        if freq < min_frequency:
            continue
        positions = [p for _, p in hits]
        competitors.append({
            "domain":            domain,
            "frequency":         freq,
            "avg_position":      round(sum(positions) / len(positions), 1),
            "best_position":     min(positions),
            "keywords_found_in": [k for k, _ in hits],
        })

    competitors.sort(key=lambda c: (-c["frequency"], c["avg_position"]))
    return competitors, errors
