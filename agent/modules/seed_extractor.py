"""
Smart seed-keyword extraction for SEO competitor discovery.

Strategy (in priority order):
  1. Walk sitemap.xml → extract category slugs from URL paths
     (e.g., /collections/diamond-rings → "diamond rings")
  2. Combine parent/child paths (e.g., /diamond + /diamond/rings → "diamond rings")
  3. Score by frequency: a slug that appears across many URLs is a real category
  4. Fall back to homepage parsing if sitemap has no signal

This is much more reliable than scraping H1/H2/nav text because category URLs
are a deliberate, stable structure maintained by every commerce site.
"""

import re
from collections import Counter
from urllib.parse import urljoin, urlparse

import requests


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Path segments that are NEVER useful as keywords
_PATH_NOISE = {
    "media", "static", "assets", "images", "img", "css", "js", "wp-content",
    "wp-admin", "wp-includes", "node_modules",
    "sitemap", "robots", "feed", "rss", "atom",
    "page", "pages", "category", "categories", "collection", "collections",
    "product", "products", "shop", "store", "item", "items",
    "tag", "tags", "archive", "archives", "feed",
    "build-your-own-ring", "build-your-own", "compare", "wishlist",
    "account", "login", "register", "checkout", "cart", "search",
    "blog", "news", "article", "articles", "post", "posts",
    "about", "contact", "help", "support", "faq", "policy", "policies",
    "privacy", "terms", "shipping", "returns", "track-order",
    "offers", "deals", "sale", "promotions", "campaign",
    "build", "design", "customize", "configurator",
    "size-guide", "care-guide", "gift-card", "store-locator",
    "mobile", "amp", "api", "graphql",
}

# Slugs that look like dates, IDs, or skus — never seeds
_NOISE_PATTERN = re.compile(r"^(\d+|\d{4}-\d{2}-\d{2}|sku-?\d+|[a-f0-9]{8,})$")


def _fetch(url: str, timeout: int = 15) -> str | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except requests.RequestException:
        pass
    return None


def _walk_sitemap(base_url: str, max_urls: int = 5000) -> list[str]:
    """Recursively walk sitemap_index → individual sitemaps → page URLs."""
    base = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"

    urls: list[str] = []
    visited: set[str] = set()
    queue = [
        urljoin(base, "/sitemap.xml"),
        urljoin(base, "/sitemap_index.xml"),
        urljoin(base, "/sitemap-index.xml"),
    ]

    while queue and len(urls) < max_urls:
        sm_url = queue.pop(0)
        if sm_url in visited:
            continue
        visited.add(sm_url)

        text = _fetch(sm_url)
        if not text:
            continue

        # Sub-sitemap references
        for m in re.finditer(r"<sitemap>.*?<loc>([^<]+)</loc>.*?</sitemap>", text, re.S):
            queue.append(m.group(1).strip())

        # Page URLs
        for m in re.finditer(r"<url>.*?<loc>([^<]+)</loc>.*?</url>", text, re.S):
            urls.append(m.group(1).strip())
            if len(urls) >= max_urls:
                break

    return urls


def _slug_to_keyword(slug: str) -> str:
    """Convert URL slug to plain-English keyword."""
    s = slug.replace("-", " ").replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s).lower()
    return s


def _is_useful_segment(seg: str) -> bool:
    if not seg or seg in _PATH_NOISE: return False
    if _NOISE_PATTERN.match(seg): return False
    if len(seg) < 3 or len(seg) > 50: return False
    if seg.isdigit(): return False
    return True


# Known category-page URL prefixes per CMS. The slug AFTER these prefixes is
# the category/keyword we want.
_CATEGORY_PREFIXES = (
    "collections",   # Shopify
    "collection",
    "category",
    "categories",
    "shop",
    "shop-by",
    "browse",
    "c",             # Magento short
    "department",
    "departments",
    "store",
)


def _category_slug(path: str) -> str | None:
    """If path matches a category-page pattern, return the category slug."""
    segs = [s for s in path.strip("/").split("/") if s]
    if not segs: return None

    # Pattern A: /collections/SLUG, /category/SLUG, etc.
    if segs[0].lower() in _CATEGORY_PREFIXES and len(segs) >= 2:
        slug = segs[1]
        if _is_useful_segment(slug):
            return slug

    # Pattern B: top-level category pages — /SLUG with depth 1, useful slug
    if len(segs) == 1 and _is_useful_segment(segs[0]):
        return segs[0]

    # Pattern C: /CATEGORY/SUBCATEGORY (depth 2) where both are useful
    # e.g., /diamond/rings on ORRA → "diamond rings"
    if len(segs) == 2 and _is_useful_segment(segs[0]) and _is_useful_segment(segs[1]):
        return f"{segs[0]}-{segs[1]}"

    return None


def _looks_like_product_url(path: str) -> bool:
    """Heuristic: distinguish product URLs from category pages."""
    segs = [s for s in path.strip("/").split("/") if s]
    if not segs: return False
    # Shopify: /products/X = product (single item), /collections/X = category
    if segs[0].lower() == "products": return True
    # Many product slugs are very long (5+ words) or contain SKUs/numbers
    last = segs[-1]
    word_count = len(last.split("-"))
    return word_count >= 5 or any(c.isdigit() for c in last)


def extract_seeds_from_sitemap(client_url: str, top_n: int = 8) -> list[str]:
    """
    Walk sitemap → identify URLs matching category-page patterns →
    extract slugs as keywords, ranked by how many child URLs sit under each.
    """
    if not client_url.startswith(("http://", "https://")):
        client_url = "https://" + client_url.strip()

    urls = _walk_sitemap(client_url)
    if not urls:
        return []

    # Strategy:
    #  - Candidate categories = paths that match _category_slug() AND aren't products
    #  - Score by: (count of OTHER URLs that have this slug as a parent path component) × novelty
    category_candidates: dict[str, int] = {}  # slug → score

    for u in urls:
        path = urlparse(u).path
        if _looks_like_product_url(path): continue
        slug = _category_slug(path)
        if slug:
            category_candidates[slug] = category_candidates.get(slug, 0) + 1

    # Boost: count how many URLs have this slug somewhere in their path
    # (a real category will have many children under it)
    for u in urls:
        path = urlparse(u).path.lower()
        for slug in list(category_candidates.keys()):
            if f"/{slug}/" in path or path.endswith(f"/{slug}"):
                category_candidates[slug] = category_candidates.get(slug, 0) + 1

    # Filter: drop slugs that didn't accumulate evidence (likely one-off pages)
    scored = [(s, c) for s, c in category_candidates.items() if c >= 3]
    scored.sort(key=lambda x: -x[1])

    seeds: list[str] = []
    seen: set[str] = set()
    for slug, _ in scored:
        kw = _slug_to_keyword(slug)
        # Drop overly generic single-letter / 1-word terms unless meaningful
        if len(kw) < 4: continue
        if kw in seen: continue
        seen.add(kw)
        seeds.append(kw)
        if len(seeds) >= top_n:
            break

    return seeds


def google_suggest(seed: str, country: str = "in") -> list[str]:
    """Free, no-auth Google Suggest API. Useful for query expansion."""
    try:
        r = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "q": seed, "gl": country, "hl": "en"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                return data[1][:10]
    except (requests.RequestException, ValueError):
        pass
    return []


def extract_seeds(client_url: str, *, top_n: int = 8, expand: bool = False) -> dict:
    """
    Returns {"seeds": [...], "source": "sitemap|homepage|none", "raw_count": int}
    """
    sitemap_seeds = extract_seeds_from_sitemap(client_url, top_n=top_n)
    if sitemap_seeds:
        result = {"seeds": sitemap_seeds, "source": "sitemap", "raw_count": len(sitemap_seeds)}
        if expand and sitemap_seeds:
            # Expand top seed via Google Suggest for richer competitor discovery
            expansion = google_suggest(sitemap_seeds[0])
            result["expansion"] = expansion[:5]
        return result

    # Fallback: homepage parsing
    from .competitor_finder import _seed_keywords_from_homepage
    home_seeds = _seed_keywords_from_homepage(client_url, max_keywords=top_n)
    return {
        "seeds": home_seeds,
        "source": "homepage" if home_seeds else "none",
        "raw_count": len(home_seeds),
    }


if __name__ == "__main__":
    import sys, json
    urls = sys.argv[1:] or ["https://www.orra.co.in/", "vinodcookware.com", "myborosil.com"]
    for url in urls:
        print(f"\n=== {url} ===")
        result = extract_seeds(url, top_n=8, expand=True)
        print(json.dumps(result, indent=2))
