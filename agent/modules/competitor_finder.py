"""
Given a client URL, suggests SEO competitors via Google SERP analysis.
Uses SearchAPI.io (legacy serp_client) — keyed by SEARCHAPI_KEY env var.

Strategy:
  1. Crawl client homepage → extract candidate seed keywords from
     <title>, h1/h2, meta description (lightweight NLP).
  2. Run those keywords through SerpAPI → collect domains that recur in top 10.
  3. Filter via the existing blocklist (Amazon, Wikipedia, news sites, etc.).
  4. Return top N domains by frequency.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from agent.services.serp_client import fetch_competitors
from agent.services.ahrefs_client import (
    organic_competitors as ahrefs_organic_competitors,
    site_metrics as ahrefs_site_metrics,
    is_configured as ahrefs_configured,
    country_code as ahrefs_country_code,
)
from agent.modules.competitor_classifier import classify as classify_competitor


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
    "at", "by", "from", "as", "is", "are", "be", "this", "that", "your",
    "our", "we", "us", "you", "best", "top", "buy", "shop", "online",
    "home", "page", "site", "website", "official", "india", "in", "usa",
}

# Nav/UI/account/checkout terms that look like keywords but aren't useful seeds.
_UI_BLOCKLIST = {
    "cart", "login", "logout", "register", "signup", "sign up", "sign in",
    "account", "my account", "wishlist", "checkout", "subtotal", "user",
    "profile", "settings", "menu", "search", "filter", "sort", "find store",
    "find a store", "store locator", "locate store", "track order",
    "about", "about us", "contact", "contact us", "help", "support", "faq",
    "blog", "news", "privacy", "terms", "policy", "policies", "shipping",
    "returns", "return", "refund", "order status", "lets get signed",
    "let's get signed", "subscribe save", "subscribe", "newsletter", "follow us",
    "read post", "read more", "view all", "show more", "load more",
    "recently viewed", "trending", "featured", "new arrivals",
    "schedule demo", "book demo", "request demo", "free trial", "get started",
    "contact sales", "talk to sales", "pricing", "search for", "search results",
    "cart empty", "your cart", "your bag", "skip content", "skip to content",
    "click here", "learn more", "explore now", "shop now", "buy now",
    "continue shopping", "back top", "back to top", "all rights reserved",
}

# Phrases that START with these words are usually CTAs/instructions, not seeds.
_CTA_STARTS = ("lets ", "let's ", "find ", "click ", "view ", "see ", "go to ",
               "watch ", "discover ", "explore ", "browse ", "search ", "shop ",
               "get ", "join ", "follow ", "read ", "learn ", "subscribe ",
               "your ", "our ", "we ", "you ", "all ", "more ", "skip ")


from agent.services.config import get_secret


def _load_env():  # back-compat shim
    pass


def _seed_keywords_from_homepage(url: str, max_keywords: int = 6) -> list[str]:
    """Heuristic: extract category/product terms from title, h1, h2 of homepage."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.strip()

    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    candidates: list[str] = []

    # Strongest signal: meta description (often summarizes what the site sells)
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        candidates.append(meta_desc["content"][:200])

    # OG title — usually brand-stripped product/service tagline
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        candidates.append(og["content"])

    # Page title — last (often brand-heavy)
    title = soup.find("title")
    if title and title.string:
        candidates.append(title.string)

    # H1/H2 typically have category labels
    for tag in soup.find_all(["h1", "h2"])[:10]:
        candidates.append(tag.get_text(strip=True))

    # Category nav links — bias toward URL paths like /collections/X, /category/X, /products/X
    for a in soup.find_all("a", href=True)[:80]:
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if 3 <= len(text) <= 30 and not text.startswith(("http", "/")):
            # Boost weight of links that look like categories
            if re.search(r"/(collection|category|categories|products|shop)/", href, re.I):
                candidates.insert(0, text)
            else:
                candidates.append(text)

    domain = urlparse(url).netloc.replace("www.", "").split(".")[0].lower()

    seen: set[str] = set()
    keywords: list[str] = []
    for raw in candidates:
        clean = re.sub(r"[^a-zA-Z\s-]", " ", raw).lower().strip()
        if not clean: continue
        if domain in clean:
            clean = clean.replace(domain, "").strip()
        words = [w for w in clean.split() if w not in _STOPWORDS and len(w) > 2]
        # Require ≥2 words (single words are usually brands or generic nouns
        # that produce noisy SERPs). Cap at 4.
        if 2 <= len(words) <= 4:
            kw = " ".join(words)
            # Reject CTAs and UI strings
            if kw in _UI_BLOCKLIST: continue
            if any(b in kw for b in _UI_BLOCKLIST): continue
            if any(kw.startswith(s.strip()) for s in _CTA_STARTS): continue
            # Reject all-stopword combos that slipped through
            if kw and kw not in seen:
                seen.add(kw)
                keywords.append(kw)
        if len(keywords) >= max_keywords:
            break

    return keywords[:max_keywords]


def find_competitors(
    client_url: str,
    *,
    seed_keywords: list[str] | None = None,
    location: str = "India",
    top_n: int = 5,
    prefer_ahrefs: bool = True,
) -> dict:
    """
    Return:
      {"seed_keywords": [...], "competitors": [...], "source": "ahrefs"|"serpapi", "errors": [...]}

    When `prefer_ahrefs=True` and AHREFS_API_TOKEN is set, uses Ahrefs
    organic-competitors endpoint (~210 units, much higher quality).
    Falls back to SerpAPI seed-based discovery otherwise.
    """
    _load_env()

    # ── Path 1: Ahrefs MCP — keyword-overlap based, best quality ──────────
    # Ahrefs doesn't need seed keywords (it uses its own keyword universe).
    # Always prefer Ahrefs when configured, even if user supplied seeds.
    if prefer_ahrefs and ahrefs_configured():
        country = ahrefs_country_code(location)
        result = ahrefs_organic_competitors(client_url, country=country, limit=top_n + 5)
        if result["competitors"]:
            comps = []
            for c in result["competitors"][:top_n + 5]:
                domain = c["competitor_domain"]
                # Classify as brand/retailer/marketplace/reference (cheap — known
                # domains classified instantly; unknowns crawl homepage briefly)
                ctype = classify_competitor(domain, deep=True)
                comps.append({
                    "domain":           domain,
                    "type":             ctype,
                    "keywords_common":  c.get("keywords_common", 0),
                    "keywords_total":   c.get("keywords_competitor", 0),
                    "domain_rating":    c.get("domain_rating", 0),
                    "traffic":          c.get("traffic", 0),
                    "frequency":        c.get("keywords_common", 0),  # back-compat for UI
                    "avg_position":     0,
                    "best_position":    0,
                    "keywords_found_in": [],
                })

            # Also fetch the client's own metrics so the analyst can compare
            client_metrics = ahrefs_site_metrics(client_url, country=country)
            client_row = None
            if "error" not in client_metrics:
                client_row = {
                    "domain":         client_metrics["target"],
                    "is_client":      True,
                    "keywords_total": client_metrics["org_keywords"],
                    "traffic":        client_metrics["org_traffic"],
                }

            # ── Positioning-aware LLM peer-brand discovery ─────────────────
            # Always ask Gemini for peer brands (free). Only validate via Ahrefs
            # site-metrics for domains NOT already in Ahrefs results — so cost
            # scales with disagreement between Ahrefs and LLM:
            #   - Kenstar (LLM agrees with Ahrefs)  → 0 extra units
            #   - Jaypore (LLM disagrees on positioning) → ~200 units
            #   - HyperX (LLM provides what Ahrefs missed) → ~250 units
            from agent.modules.peer_brand_finder import discover_and_validate as discover_peers
            from agent.modules.business_model_detector import detect as detect_bm
            from agent.modules.seed_extractor import extract_seeds_from_sitemap

            peer_result = {"category_understood": "", "validated_peers": []}
            peer_units = 0
            llm_skip_reason = ""

            try:
                bm = detect_bm(client_url)
                seeds = extract_seeds_from_sitemap(client_url, top_n=5)
                niche_hint = ", ".join(seeds) if seeds else ""
                client_name_guess = client_url.replace("https://","").replace("http://","").strip("/").split("/")[0].split(".")[0].title()

                ahrefs_domains = {c["domain"] for c in comps}
                peer_result = discover_peers(
                    client_url=client_url,
                    client_name=client_name_guess,
                    business_model=bm.primary,
                    niche_hint=niche_hint,
                    location=location,
                    existing_domains=ahrefs_domains,   # dedupe — only validate new ones
                    max_validate=6,
                )
                peer_units = peer_result.get("units_cost", 0)

                # Merge new LLM peers into the candidate list
                for p in peer_result.get("validated_peers", []):
                    if p["domain"] not in ahrefs_domains:
                        comps.append({
                            "domain":           p["domain"],
                            "type":             "brand",
                            "keywords_common":  0,
                            "keywords_total":   p.get("keywords_total", 0),
                            "domain_rating":    p.get("domain_rating", 0),
                            "traffic":          p.get("traffic", 0),
                            "frequency":        0,
                            "avg_position":     0,
                            "best_position":    0,
                            "keywords_found_in": [],
                            "source":           p.get("source", "llm"),
                            "rationale":        p.get("rationale", ""),
                        })

                # Free-call note: if 0 new peers added, Gemini agrees with Ahrefs
                if peer_units == 0 and peer_result.get("validated_peers", []):
                    llm_skip_reason = "Gemini's peer suggestions all already in Ahrefs — positioning confirmed"
                elif peer_result.get("llm_source") == "skipped":
                    llm_skip_reason = "Gemini unavailable (rate-limit) — relying on Ahrefs only"
            except Exception:
                pass

            return {
                "seed_keywords":       [],
                "client_row":          client_row,
                "competitors":         comps[:top_n + len(peer_result.get("validated_peers", []))],
                "source":              "ahrefs+llm" if peer_units > 0 else "ahrefs",
                "category_understood": peer_result.get("category_understood", ""),
                "llm_peers_added":     len(peer_result.get("validated_peers", [])),
                "llm_skipped_reason":  llm_skip_reason,
                "units_cost":          result["units_cost"] + (client_metrics.get("units_cost", 0) if client_row else 0) + peer_units,
                "errors":              [] if client_row else [client_metrics.get("error", "")] if "error" in client_metrics else [],
            }
        # If Ahrefs returned nothing or failed, fall through to SerpAPI

    # ── Path 2: SerpAPI seed-based fallback ───────────────────────────────
    api_key = get_secret("SEARCHAPI_KEY")
    if not api_key:
        return {
            "seed_keywords": [],
            "competitors": [],
            "source": "none",
            "errors": ["No competitor source available — set AHREFS_API_TOKEN (preferred) or SEARCHAPI_KEY in .env"],
        }

    if not seed_keywords:
        # Smart extractor: sitemap-based + Google Suggest expansion
        from .seed_extractor import extract_seeds, google_suggest
        sitemap_result = extract_seeds(client_url, top_n=6)
        seed_keywords = list(sitemap_result.get("seeds", []))
        # Expand top 2 seeds via Google Suggest for richer SERP coverage
        if seed_keywords:
            for s in seed_keywords[:2]:
                for sugg in google_suggest(s, country="in" if location.lower() == "india" else "us")[:3]:
                    if sugg not in seed_keywords and len(sugg.split()) >= 2:
                        seed_keywords.append(sugg)
        # Final fallback: homepage parsing
        if not seed_keywords:
            seed_keywords = _seed_keywords_from_homepage(client_url)
    if not seed_keywords:
        return {
            "seed_keywords": [],
            "competitors": [],
            "source": "serpapi",
            "errors": ["Could not extract seed keywords — pass them manually via seed_keywords"],
        }

    client_domain = urlparse(
        client_url if "://" in client_url else f"https://{client_url}"
    ).netloc.replace("www.", "").lower()

    # min_frequency=1 because we only feed a handful of seeds; a relevant
    # competitor that ranks for even one of them is worth surfacing.
    comps, errors = fetch_competitors(
        keywords=seed_keywords,
        api_key=api_key,
        location=location,
        num_results=10,
        min_frequency=1,
    )

    # Drop the client itself if it shows up in its own SERPs
    comps = [c for c in comps if c["domain"] != client_domain]

    return {
        "seed_keywords": seed_keywords,
        "competitors": comps[:top_n],
        "source": "serpapi",
        "errors": errors,
    }


if __name__ == "__main__":
    import sys, json
    url = sys.argv[1] if len(sys.argv) > 1 else "vinodcookware.com"
    result = find_competitors(url)
    print(json.dumps(result, indent=2))
