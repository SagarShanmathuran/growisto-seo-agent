"""
Website analyser + keyword generator for competitor discovery.

Flow:
  1. Scrape the client website → extract specific product/service terms
  2. Feed those terms into Google Autocomplete (via SearchAPI) → get real queries
     people actually search (guaranteed search volume, buyer intent)
  3. Those real queries are used as seeds for SERP competitor discovery
"""

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from collections import Counter


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Words that appear in headings/nav everywhere but mean nothing as a keyword
_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "our", "your", "we", "you", "us", "my",
    "all", "this", "that", "it", "its", "more", "get", "new",
    "home", "page", "site", "web",
    "about", "contact", "privacy", "terms", "policy",
    "login", "register", "account", "cart", "checkout", "wishlist",
    "search", "view", "read", "click", "learn", "know", "see",
}

_UI_NOISE = {
    "collections", "category", "categories", "products", "product", "shop",
    "store", "all", "featured", "new arrivals", "sale", "deals", "offer",
    "offers", "trending", "popular", "explore", "browse", "discover",
    "best sellers", "view all", "see all", "read more", "learn more",
    "menu", "navigation", "header", "footer", "blog", "news", "events",
}

# Autocomplete suggestions containing these are informational, not buyer intent
_INFO_SIGNALS = {
    "how to", "how do", "how can", "what is", "what are", "what does",
    "why is", "why do", "when to", "where to find",
    "meaning", "definition", "wikipedia", "history", "explain",
    "recipe", "tutorial", "learn", "guide", "tips", "tricks", "advice",
    "difference between", "vs reddit", "forum", "quora",
}

_GL_MAP = {
    "India": "in", "United Kingdom": "gb", "Australia": "au",
    "Canada": "ca", "Germany": "de", "UAE": "ae",
    "France": "fr", "Singapore": "sg",
}


# ── Site scraper ──────────────────────────────────────────────────────────────

def _fetch_soup(url: str):
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=14, allow_redirects=True)
        return BeautifulSoup(resp.text, "lxml")
    except Exception:
        return None


def _clean(text: str) -> str:
    text = re.split(r"[|\-—–•·]", text)[0]
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _is_product_term(phrase: str, brand: str) -> bool:
    low = phrase.lower().strip()
    if not low or low in _UI_NOISE:
        return False
    if brand and brand in low.replace(" ", ""):
        return False
    words = low.split()
    if not (1 <= len(words) <= 5):
        return False
    meaningful = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
    return len(meaningful) >= 1


def scrape_product_terms(url: str) -> dict:
    """
    Scrape the website and extract the specific product/service terms it sells.
    Returns { product_terms: list[str], scraped: bool, title: str, error: str|None }
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    soup = _fetch_soup(url)
    if soup is None:
        return {"product_terms": [], "scraped": False, "title": "", "error": "Could not fetch the site."}

    title = (soup.find("title") or soup.new_tag("x")).get_text(strip=True)
    meta_kw = (soup.find("meta", attrs={"name": "keywords"}) or {}).get("content", "")

    h1s = [t.get_text(strip=True) for t in soup.find_all("h1")]
    h2s = [t.get_text(strip=True) for t in soup.find_all("h2")]

    # Navigation menu items — strongest signal for what the site sells
    nav_texts: list[str] = []
    for nav in soup.find_all(["nav", "header"]):
        for a in nav.find_all("a"):
            txt = a.get_text(strip=True)
            if txt and 1 <= len(txt.split()) <= 5:
                nav_texts.append(txt)

    # URL slug terms — actual product/category page names
    base_host = urlparse(url).netloc.replace("www.", "")
    brand = base_host.split(".")[0].lower()
    slug_terms: list[str] = []
    internal_links: list[str] = []

    for a in soup.find_all("a", href=True)[:200]:
        href = a["href"]
        parsed = urlparse(href if href.startswith("http") else f"https://{base_host}{href}")
        if base_host not in parsed.netloc:
            continue
        full_url = f"https://{parsed.netloc}{parsed.path}"
        if full_url != url and full_url not in internal_links:
            internal_links.append(full_url)
        for part in [p for p in parsed.path.strip("/").split("/") if p]:
            clean = part.replace("-", " ").replace("_", " ").strip()
            if 1 <= len(clean.split()) <= 4 and not any(c.isdigit() for c in clean):
                if clean.lower() not in _UI_NOISE:
                    slug_terms.append(clean)

    # Follow up to 3 category/product pages for deeper signal
    priority_paths = [
        "products", "product", "solutions", "services", "schemes",
        "categories", "category", "collections", "offerings", "funds",
        "range", "shop", "what-we-do", "industries",
    ]
    extra_nav, extra_slugs = [], []
    picked = 0
    for link in internal_links:
        if picked >= 3:
            break
        path_lower = link.lower()
        if not any(f"/{p}" in path_lower or path_lower.endswith(f"/{p}") for p in priority_paths):
            continue
        sub = _fetch_soup(link)
        if sub is None:
            continue
        picked += 1
        for nav in sub.find_all(["nav", "header"]):
            for a in nav.find_all("a"):
                txt = a.get_text(strip=True)
                if txt and 1 <= len(txt.split()) <= 5:
                    extra_nav.append(txt)
        for a2 in sub.find_all("a", href=True)[:80]:
            href = a2["href"]
            p2 = urlparse(href if href.startswith("http") else f"https://{base_host}{href}")
            if base_host not in p2.netloc:
                continue
            for part in [p for p in p2.path.strip("/").split("/") if p]:
                clean = part.replace("-", " ").replace("_", " ").strip()
                if 1 <= len(clean.split()) <= 4 and not any(c.isdigit() for c in clean):
                    if clean.lower() not in _UI_NOISE:
                        extra_slugs.append(clean)

    # Score and rank product terms
    bag: Counter = Counter()

    for slug in slug_terms + extra_slugs:
        clean = _clean(slug)
        if _is_product_term(clean, brand):
            bag[clean] += 4   # URL slugs = highest signal

    for nav in nav_texts + extra_nav:
        clean = _clean(nav)
        if _is_product_term(clean, brand):
            bag[clean] += 3   # Nav = strong signal

    for kw in (meta_kw or "").split(","):
        clean = _clean(kw.strip())
        if _is_product_term(clean, brand):
            bag[clean] += 3

    for h in h1s:
        clean = _clean(h)
        if _is_product_term(clean, brand) and len(clean.split()) <= 4:
            bag[clean] += 2

    for h in h2s:
        clean = _clean(h)
        if _is_product_term(clean, brand) and 2 <= len(clean.split()) <= 3:
            bag[clean] += 1

    # Deduplicate: prefer more specific terms over generic subsets
    ranked = [t for t, _ in bag.most_common(30)]
    filtered: list[str] = []
    for term in ranked:
        is_subset = any(term != other and term in other for other in ranked)
        if not is_subset:
            filtered.append(term)

    product_terms = filtered[:15]
    return {
        "product_terms": product_terms,
        "scraped": True,
        "title": title,
        "error": None if product_terms else "No product terms found — site may be JS-rendered.",
    }


# ── Google Autocomplete expansion ────────────────────────────────────────────

def get_real_keywords_from_autocomplete(
    product_terms: list[str],
    serp_api_key: str,
    location: str = "United States",
    fallback_niche: str = "",
) -> list[str]:
    """
    Feed product/service terms into Google Autocomplete to get REAL search queries
    people type. These have guaranteed search volume and buyer intent.

    Uses the SearchAPI key the user already has — no extra setup needed.
    """
    endpoint = "https://www.searchapi.io/api/v1/search"
    gl = _GL_MAP.get(location, "us")

    # If we have no product terms, fall back to niche
    seeds = product_terms[:8] if product_terms else [fallback_niche]
    if not any(seeds):
        return []

    all_suggestions: list[str] = []
    seen: set[str] = set()

    for term in seeds:
        if not term.strip():
            continue

        params = {
            "engine":  "google_autocomplete",
            "q":       term.strip(),
            "gl":      gl,
            "api_key": serp_api_key,
        }
        try:
            resp = requests.get(endpoint, params=params, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            suggestions = data.get("suggestions", [])

            for s in suggestions[:8]:
                text = s.get("value", "").lower().strip()
                if not text or text in seen:
                    continue
                # Skip informational queries
                if any(sig in text for sig in _INFO_SIGNALS):
                    continue
                # Keep 2-6 word queries
                words = text.split()
                if not (2 <= len(words) <= 6):
                    continue
                seen.add(text)
                all_suggestions.append(text)
        except Exception:
            continue

    return all_suggestions[:20]


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_website(url: str, claude_api_key: str = "") -> dict:
    """Legacy wrapper — just runs the scraper portion."""
    result = scrape_product_terms(url)
    return {
        "keywords":         result["product_terms"],
        "detected_products": result["product_terms"],
        "source":           "rule-based",
        "error":            result["error"],
    }


def suggest_keywords(url: str, claude_api_key: str = "") -> dict:
    """Legacy alias."""
    return analyze_website(url, claude_api_key)
