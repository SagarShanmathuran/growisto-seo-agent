"""
Auto-extract Average Order Value (AOV) by sampling product prices from a site.

Strategy (in priority order):
  1. Pull /sitemap.xml → find product URLs (matching /product/, /products/, /collections/)
  2. Fetch up to N product pages
  3. Parse JSON-LD `Product.offers.price` (most accurate)
  4. Fallback: regex search for currency patterns (₹1,234 / $19.99)
  5. Return median price + sample count + currency

Skips for B2B sites where pricing isn't public — returns None.
"""

import json
import random
import re
import statistics
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_PRODUCT_URL_PATTERNS = re.compile(r"/(product|products|collections|shop|item)/", re.I)

_CURRENCY_PATTERNS = [
    (re.compile(r"₹\s?([\d,]+(?:\.\d{1,2})?)"),               "INR"),
    (re.compile(r"Rs\.?\s?([\d,]+(?:\.\d{1,2})?)", re.I),     "INR"),
    (re.compile(r"INR\s?([\d,]+(?:\.\d{1,2})?)"),             "INR"),
    (re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)"),              "USD"),
    (re.compile(r"USD\s?([\d,]+(?:\.\d{1,2})?)"),             "USD"),
    (re.compile(r"€\s?([\d,]+(?:\.\d{1,2})?)"),               "EUR"),
    (re.compile(r"£\s?([\d,]+(?:\.\d{1,2})?)"),               "GBP"),
]


def _fetch(url: str, timeout: int = 15) -> str | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except requests.RequestException:
        pass
    return None


def _product_urls_from_sitemap(base_url: str, limit: int = 500) -> list[str]:
    """Walk sitemap (handles sitemap_index recursion)."""
    base = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    candidates = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-products.xml"]

    urls: list[str] = []
    visited: set[str] = set()
    queue = [urljoin(base, c) for c in candidates]

    while queue and len(urls) < limit:
        sm_url = queue.pop(0)
        if sm_url in visited:
            continue
        visited.add(sm_url)

        text = _fetch(sm_url)
        if not text:
            continue

        # Sitemap index → recurse
        for m in re.finditer(r"<sitemap>.*?<loc>([^<]+)</loc>.*?</sitemap>", text, re.S):
            sub = m.group(1).strip()
            if "product" in sub.lower() or "collection" in sub.lower() or "sitemap" in sub.lower():
                queue.append(sub)

        # Page URLs
        for m in re.finditer(r"<url>.*?<loc>([^<]+)</loc>.*?</url>", text, re.S):
            page_url = m.group(1).strip()
            if _PRODUCT_URL_PATTERNS.search(page_url) and "/collections/" not in page_url \
               and not page_url.endswith(("/products", "/products/")):
                urls.append(page_url)
                if len(urls) >= limit:
                    break

    return urls


def _price_from_jsonld(html: str) -> float | None:
    """Look for Product schema with offers.price."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict): continue
                graph = item.get("@graph") if "@graph" in item else [item]
                for node in (graph if isinstance(graph, list) else [graph]):
                    if not isinstance(node, dict): continue
                    t = node.get("@type")
                    if isinstance(t, list): t = next((x for x in t if isinstance(x, str)), "")
                    if t and "product" in t.lower():
                        offers = node.get("offers")
                        if isinstance(offers, dict):
                            p = offers.get("price") or offers.get("lowPrice")
                            if p: return float(str(p).replace(",", ""))
                        if isinstance(offers, list) and offers:
                            p = offers[0].get("price")
                            if p: return float(str(p).replace(",", ""))
        except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
            pass
    return None


def _price_from_regex(html: str) -> tuple[float, str] | None:
    """Fallback: take the first plausible price match in page body."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    for pattern, currency in _CURRENCY_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                value = float(m.group(1).replace(",", ""))
                if 1 <= value <= 10_000_000:    # sanity
                    return value, currency
            except ValueError:
                continue
    return None


def extract_aov(client_url: str, *, sample_size: int = 30, verbose: bool = False) -> dict:
    """
    Returns:
      {
        "median_aov": float | None,
        "currency": "INR" | "USD" | ...,
        "sample_size": int,
        "products_found": int,
        "method": "json-ld" | "regex" | "none",
        "errors": [str],
      }
    """
    if not client_url.startswith(("http://", "https://")):
        client_url = "https://" + client_url.strip()

    errors: list[str] = []

    product_urls = _product_urls_from_sitemap(client_url, limit=500)
    if verbose: print(f"  [aov] found {len(product_urls)} product URLs in sitemap")

    if not product_urls:
        return {"median_aov": None, "currency": None, "sample_size": 0,
                "products_found": 0, "method": "none",
                "errors": ["No product URLs found via sitemap"]}

    # Random sample (avoid bias toward the first ones in sitemap)
    sample = random.sample(product_urls, min(sample_size, len(product_urls)))

    prices: list[float] = []
    currencies: list[str] = []
    method_used = "none"

    for url in sample:
        html = _fetch(url, timeout=12)
        if not html: continue

        p = _price_from_jsonld(html)
        if p is not None and 1 <= p <= 10_000_000:
            prices.append(p)
            method_used = "json-ld"
            continue

        result = _price_from_regex(html)
        if result:
            prices.append(result[0])
            currencies.append(result[1])
            if method_used == "none":
                method_used = "regex"

    if not prices:
        return {"median_aov": None, "currency": None, "sample_size": len(sample),
                "products_found": len(product_urls), "method": "none",
                "errors": errors + ["No prices extracted from sampled product pages"]}

    sorted_prices = sorted(prices)
    n = len(sorted_prices)

    def _pct(p: float) -> float:
        idx = max(0, min(n - 1, int(p * (n - 1))))
        return round(sorted_prices[idx], 2)

    median = round(statistics.median(prices), 2)
    p25    = _pct(0.25)
    p75    = _pct(0.75)
    currency = max(set(currencies), key=currencies.count) if currencies else "INR"

    # Recommended AOV for SEO ROI: use the 25th percentile (SEO-acquired customers
    # typically convert on entry/mid-tier products, not luxury long-tail).
    recommended_aov = p25 if (max(prices) / max(min(prices), 1)) > 50 else median

    return {
        "median_aov":       median,
        "p25_aov":          p25,
        "p75_aov":          p75,
        "recommended_aov":  recommended_aov,
        "currency":         currency,
        "sample_size":      len(prices),
        "products_found":   len(product_urls),
        "method":           method_used,
        "min_price":        round(min(prices), 2),
        "max_price":        round(max(prices), 2),
        "price_range_ratio": round(max(prices) / max(min(prices), 1), 1),
        "errors":           errors,
    }


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "vinodcookware.com"
    result = extract_aov(url, sample_size=20, verbose=True)
    print(json.dumps(result, indent=2))
