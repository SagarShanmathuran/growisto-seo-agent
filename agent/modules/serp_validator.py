"""
SERP-based competitor validation — third confidence layer.

For a given client + niche, ask Gemini to enumerate 5-7 high-intent
transactional keywords, then run each through SearchAPI's Google SERP
endpoint to find which brands actually rank in the top 10. Brands that
appear in multiple SERPs are the genuine ranking competitors.

This catches cases where Ahrefs keyword-overlap + Gemini suggestion both
miss because the analyst's sense of "competitor" is anchored to live
SERP behaviour (which is what the prospect's customers actually see).

Cost: 1 Gemini call (free) + N SerpAPI calls (₹0.30-0.80 each typically).
For 5-7 keywords ≈ ₹1.50-5.60 per validation. Opt-in only.
"""

import os
import json
import re
import time
from urllib.parse import urlparse

import requests

from agent.services.config import get_secret
from agent.services.serp_client import _is_business_competitor   # reuse blocklist


_LOC_HINTS = {
    "india":          {"google_domain": "google.co.in", "gl": "in", "hl": "en"},
    "united kingdom": {"google_domain": "google.co.uk", "gl": "uk", "hl": "en"},
    "united states":  {"google_domain": "google.com",   "gl": "us", "hl": "en"},
    "australia":      {"google_domain": "google.com.au","gl": "au", "hl": "en"},
    "canada":         {"google_domain": "google.ca",    "gl": "ca", "hl": "en"},
    "uae":            {"google_domain": "google.ae",    "gl": "ae", "hl": "en"},
    "singapore":      {"google_domain": "google.com.sg","gl": "sg", "hl": "en"},
}


_GEMINI_MODEL = "gemini-2.5-flash"
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
_SERP_ENDPOINT = "https://www.searchapi.io/api/v1/search"


_TRANSACTIONAL_KW_PROMPT = """You are an SEO analyst at Growisto. Suggest 5–7 high-intent transactional keywords that prospective customers of this client would search on Google when they are ready to buy or shortlist a vendor.

Rules:
- Focus on COMMERCIAL/TRANSACTIONAL intent (e.g., "X software", "X platform pricing", "best X for Y", "X tool", "X service"), NOT informational ("what is X", "how to X").
- Stay in the target market language and locale.
- Generic enough that multiple brands rank for them — these will be used to identify ranking competitors.
- Avoid brand-name keywords (the client's own name, or specific competitor names). We want category-level queries.

CONTEXT:
- Client: {client_name}
- URL: {client_url}
- Business model: {business_model}
- Niche / category: {niche_hint}
- Target market: {location}

Return ONLY a JSON object:
{
  "keywords": ["keyword 1", "keyword 2", ...]
}
""".strip()


def _suggest_transactional_keywords(
    *, client_url: str, client_name: str, business_model: str,
    niche_hint: str, location: str, verbose: bool = False,
) -> list[str]:
    """Ask Gemini to enumerate 5-7 transactional/commercial keywords for the niche."""
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        return []

    prompt = (_TRANSACTIONAL_KW_PROMPT
              .replace("{client_name}",    client_name or "—")
              .replace("{client_url}",     client_url)
              .replace("{business_model}", business_model or "unknown")
              .replace("{niche_hint}",     niche_hint or "(unknown)")
              .replace("{location}",       location))

    url = _GEMINI_ENDPOINT.format(model=_GEMINI_MODEL, key=api_key)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    for attempt in range(3):
        try:
            r = requests.post(url, json=body, timeout=30)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
                parsed = json.loads(text)
                kws = parsed.get("keywords", [])
                if verbose: print(f"  [serp-validator] Gemini suggested {len(kws)} kws")
                return [k for k in kws if isinstance(k, str)][:7]
            if r.status_code in (429, 503):
                if verbose: print(f"  [serp-validator] Gemini HTTP {r.status_code} — retry {attempt+1}/3")
                time.sleep(2 ** attempt)
                continue
            return []
        except Exception:
            time.sleep(2 ** attempt)
    return []


def _serp_top_domains(keyword: str, *, api_key: str, location: str = "India",
                      num: int = 10, verbose: bool = False) -> list[dict]:
    """Run a single Google SERP call via SearchAPI; return top-N organic domains."""
    geo_params = _LOC_HINTS.get(location.lower().strip(), {})
    params = {
        "engine":   "google",
        "q":        keyword,
        "location": location,
        "api_key":  api_key,
        **geo_params,
    }
    try:
        r = requests.get(_SERP_ENDPOINT, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            if verbose: print(f"  [serp-validator] '{keyword}' error: {data['error']}")
            return []
        results = []
        for item in data.get("organic_results", [])[:num]:
            domain = (item.get("domain") or "").replace("www.", "").lower().strip()
            pos = int(item.get("position", 99))
            if domain and _is_business_competitor(domain):
                results.append({"domain": domain, "position": pos, "title": item.get("title", "")})
        return results
    except (requests.RequestException, KeyError, ValueError):
        return []


def validate_via_serp(
    *,
    client_url: str,
    client_name: str,
    business_model: str,
    niche_hint: str = "",
    location: str = "India",
    keywords: list[str] | None = None,
    max_keywords: int = 6,
    verbose: bool = False,
) -> dict:
    """
    End-to-end SERP validation. Returns:
      {
        "keywords":    [the kws checked],
        "serp_results": {kw: [{domain, position}, ...]},
        "ranking_brands": {domain: {frequency, avg_position, in_kws: [kw, ...]}},
        "errors":      [str],
        "cost_estimate": float (in INR per typical SerpAPI pricing),
      }
    """
    serp_key = get_secret("SEARCHAPI_KEY")
    if not serp_key:
        return {"keywords": [], "serp_results": {}, "ranking_brands": {},
                "errors": ["SEARCHAPI_KEY not set"], "cost_estimate": 0}

    if not keywords:
        keywords = _suggest_transactional_keywords(
            client_url=client_url, client_name=client_name,
            business_model=business_model, niche_hint=niche_hint,
            location=location, verbose=verbose,
        )
    if not keywords:
        return {"keywords": [], "serp_results": {}, "ranking_brands": {},
                "errors": ["Could not generate transactional keywords (Gemini unavailable?)"],
                "cost_estimate": 0}
    keywords = keywords[:max_keywords]

    client_domain = urlparse(
        client_url if "://" in client_url else f"https://{client_url}"
    ).netloc.replace("www.", "").lower()

    # Tally domains across all SERPs
    serp_results: dict[str, list[dict]] = {}
    domain_hits: dict[str, list[tuple[str, int]]] = {}
    errors: list[str] = []

    for kw in keywords:
        rows = _serp_top_domains(kw, api_key=serp_key, location=location, verbose=verbose)
        if not rows:
            errors.append(f"No SERP results for '{kw}'")
            continue
        serp_results[kw] = rows
        for row in rows:
            d = row["domain"]
            if d == client_domain: continue   # skip the client itself
            domain_hits.setdefault(d, []).append((kw, row["position"]))

    # Build ranking-brands summary
    ranking_brands = {}
    for d, hits in domain_hits.items():
        positions = [p for _, p in hits]
        ranking_brands[d] = {
            "frequency":    len(hits),
            "avg_position": round(sum(positions) / len(positions), 1),
            "best_position": min(positions),
            "in_kws":       [k for k, _ in hits],
        }

    # Sort by frequency then by avg position
    sorted_brands = dict(sorted(
        ranking_brands.items(),
        key=lambda kv: (-kv[1]["frequency"], kv[1]["avg_position"]),
    ))

    return {
        "keywords":     keywords,
        "serp_results": serp_results,
        "ranking_brands": sorted_brands,
        "errors":       errors,
        "cost_estimate": len(keywords) * 0.5,   # ₹0.50 per SERP estimate (varies by plan)
    }


if __name__ == "__main__":
    import sys
    cli = {
        "client_url":     sys.argv[1] if len(sys.argv) > 1 else "locobuzz.com",
        "client_name":    "Locobuzz",
        "business_model": "b2b_saas",
        "niche_hint":     "social listening, customer experience, social media management platform",
        "location":       "India",
        "verbose":        True,
    }
    out = validate_via_serp(**cli)
    print(f"\nKeywords used: {out['keywords']}")
    print(f"Errors: {out['errors']}")
    print(f"\nTop ranking brands across {len(out['keywords'])} SERPs:")
    for d, info in list(out["ranking_brands"].items())[:15]:
        print(f"  {d:30s} freq={info['frequency']}  avg_pos={info['avg_position']}  best={info['best_position']}")
