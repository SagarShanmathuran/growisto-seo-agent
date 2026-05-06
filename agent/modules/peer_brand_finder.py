"""
LLM-driven peer-brand discovery — fixes the limit of Ahrefs' "keyword overlap"
algorithm, which surfaces retailers/aggregators when the client is in a brand-
keyword-heavy category (e.g., gaming peripherals: HyperX vs Razer/Logitech).

Flow:
  client URL + business model + niche → Gemini → list of brand peers
                                              → validate each via Ahrefs site-metrics
                                              → merge with Ahrefs candidates

Cost: ~50 Ahrefs units per validated brand (~250 units for 5 suggestions).
Gemini is free-tier (with template fallback if rate-limited).
"""

import json
import os
import re
from pathlib import Path

import requests


_MODEL = "gemini-2.5-flash"
# Fallback chain — when one model is rate-limited, the next typically has fresh quota
_MODEL_FALLBACKS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


from agent.services.config import get_secret


_PROMPT = """You are a senior SEO analyst at Growisto. Your client wants to do an SEO competitor analysis.

The default Ahrefs "organic-competitors" tool sorts by keyword overlap, which fails when the client is a brand whose product names don't overlap with peer brands' product names (e.g., HyperX's keywords are "hyperx cloud", "hyperx alloy"; Razer's are "razer huntsman", "razer deathadder" — no overlap, despite being direct peers).

For each request, suggest 5–8 PEER BRANDS in the same competitive category, in the same target market.

CONTEXT:
- Client: {client_name}
- URL: {client_url}
- Business model: {business_model}
- Niche / category hints (auto-detected from sitemap / homepage): {niche_hint}
- Target market: {location}
- Path-specificity: {path_hint}

RULES:
1. Suggest DIRECT BRAND PEERS — companies selling competing products to the same customers.
2. Stay within the same TIER — if client is a mid-tier brand, don't only suggest premium-tier giants.
3. Stay within the target market — if location is India, prefer brands with India presence.
4. If the URL's path is category-specific (e.g., /collections/helmets), focus peers on THAT category.
5. NEVER suggest: retailers (Amazon, Croma, Reliance Digital), marketplaces, review sites (RTings), the client itself.
6. Return real, working domains (e.g., "razer.com", "logitech.com" — not made-up URLs).
7. If you genuinely don't know the category or peers, return an empty list rather than guessing.

Return ONLY a JSON object:
{
  "category_understood":  "<1-line description of what the client sells>",
  "suggested_peers": [
    {"domain": "razer.com",      "brand_name": "Razer",      "rationale": "<1 sentence>"},
    {"domain": "logitech.com",   "brand_name": "Logitech",   "rationale": "<1 sentence>"}
  ]
}
""".strip()


def suggest_peer_brands(
    *,
    client_url: str,
    client_name: str,
    business_model: str,
    niche_hint: str = "",
    location: str = "India",
    path_hint: str = "",
    verbose: bool = False,
) -> dict:
    """
    Returns:
      {
        "category_understood": "...",
        "suggested_peers": [{"domain", "brand_name", "rationale"}, ...],
        "source": "gemini" | "skipped",
      }
    """
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        if verbose: print("  [peer-brand] GEMINI_API_KEY not set — skipping")
        return {"category_understood": "", "suggested_peers": [], "source": "skipped"}

    prompt = (_PROMPT
              .replace("{client_name}",     client_name or "—")
              .replace("{client_url}",      client_url)
              .replace("{business_model}",  business_model or "unknown")
              .replace("{niche_hint}",      niche_hint or "(unknown)")
              .replace("{location}",        location)
              .replace("{path_hint}",       path_hint or "(none — root domain)"))

    import time
    last_status = None
    last_error = ""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
    }

    # Cycle through model fallback chain — each model has its own per-day quota
    # so when 2.5-flash is 429-ed, flash-latest or 1.5-flash often still works
    for model in _MODEL_FALLBACKS:
        url = _ENDPOINT.format(model=model, key=api_key)
        try:
            r = requests.post(url, json=body, timeout=45)
            last_status = r.status_code
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
                parsed = json.loads(text)
                parsed.setdefault("category_understood", "")
                parsed.setdefault("suggested_peers", [])
                parsed["source"] = "gemini"
                parsed["model"] = model
                if verbose: print(f"  [peer-brand] {len(parsed['suggested_peers'])} suggestions via {model}")
                return parsed
            if r.status_code in (429, 503):
                if verbose: print(f"  [peer-brand] {model}: HTTP {r.status_code} — trying next model")
                time.sleep(0.5)
                continue
            last_error = f"HTTP {r.status_code}: {r.text[:100]}"
            if verbose: print(f"  [peer-brand] {model}: {last_error}")
            break
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:120]}"
            if verbose: print(f"  [peer-brand] {model}: {last_error}")
            continue

    if verbose: print(f"  [peer-brand] all models exhausted — last: {last_status or last_error}")
    return {
        "category_understood": "",
        "suggested_peers":     [],
        "source":              "skipped",
        "skip_reason":         f"Gemini unavailable across all models (last: {last_status or last_error or 'error'})",
    }


def _path_hint(client_url: str) -> str:
    """Extract URL path-specificity hint (e.g., /collections/helmets)."""
    from urllib.parse import urlparse
    p = urlparse(client_url if "://" in client_url else "https://" + client_url).path
    p = p.strip("/")
    return p[:80] if p else ""


def discover_and_validate(
    *,
    client_url: str,
    client_name: str,
    business_model: str,
    niche_hint: str = "",
    location: str = "India",
    existing_domains: set[str] | None = None,
    max_validate: int = 6,
    verbose: bool = False,
) -> dict:
    """
    End-to-end: ask Gemini for peer brands, validate each via Ahrefs site-metrics
    (skipping any already in Ahrefs results), return enriched candidate list.

    Returns:
      {
        "category_understood": "...",
        "validated_peers": [
          {"domain", "brand_name", "rationale", "type": "brand", "traffic": int,
           "keywords_total": int, "keywords_common": 0, "domain_rating": 0,
           "source": "llm"},
          ...
        ],
        "skipped_invalid":   [domains that returned no Ahrefs metrics],
        "units_cost":        int,
      }
    """
    from agent.services.ahrefs_client import (
        site_metrics, country_code, is_configured as ahrefs_configured,
    )

    suggestions = suggest_peer_brands(
        client_url=client_url, client_name=client_name,
        business_model=business_model, niche_hint=niche_hint,
        location=location, path_hint=_path_hint(client_url),
        verbose=verbose,
    )

    existing = {d.lower() for d in (existing_domains or set())}
    country = country_code(location)
    validated = []
    skipped   = []
    total_units = 0

    for s in suggestions.get("suggested_peers", [])[:max_validate]:
        dom = s.get("domain", "").strip().lower().replace("https://", "").replace("http://", "").strip("/").replace("www.", "")
        if not dom or dom in existing:
            continue

        if not ahrefs_configured():
            # No Ahrefs key — include unvalidated (analyst will assess manually)
            validated.append({
                "domain":          dom,
                "brand_name":      s.get("brand_name", dom),
                "rationale":       s.get("rationale", ""),
                "type":            "brand",
                "traffic":         0,
                "keywords_total":  0,
                "keywords_common": 0,
                "domain_rating":   0,
                "source":          "llm_unvalidated",
            })
            continue

        m = site_metrics(dom, country=country)
        total_units += m.get("units_cost", 0)
        if "error" in m or m.get("org_traffic", 0) <= 0:
            skipped.append(dom)
            continue
        validated.append({
            "domain":          dom,
            "brand_name":      s.get("brand_name", dom),
            "rationale":       s.get("rationale", ""),
            "type":            "brand",
            "traffic":         m.get("org_traffic", 0),
            "keywords_total":  m.get("org_keywords", 0),
            "keywords_common": 0,    # not measurable without an organic-keywords call
            "domain_rating":   0,    # likewise
            "source":          "llm",
        })

    return {
        "category_understood": suggestions.get("category_understood", ""),
        "validated_peers":     validated,
        "skipped_invalid":     skipped,
        "all_suggestions":     suggestions.get("suggested_peers", []),  # raw list — analyst can compare
        "units_cost":          total_units,
        "llm_source":          suggestions.get("source", "skipped"),
        "llm_skip_reason":     suggestions.get("skip_reason", ""),
    }


if __name__ == "__main__":
    # Smoke tests
    for case in [
        {"client_url":"row.hyperx.com", "client_name":"HyperX",
         "business_model":"b2c_ecommerce", "niche_hint":"gaming peripherals — keyboards, headsets, mice",
         "location":"India"},
        {"client_url":"shop.tvsmotor.com/collections/helmets", "client_name":"TVS Motor Shop",
         "business_model":"b2c_ecommerce", "niche_hint":"motorcycle helmets",
         "location":"India"},
        {"client_url":"kenstar.in", "client_name":"Kenstar",
         "business_model":"b2c_ecommerce", "niche_hint":"home appliances — coolers, mixers, fans",
         "location":"India"},
    ]:
        print(f"\n=== {case['client_name']} ===")
        r = discover_and_validate(**case, verbose=True, max_validate=4)
        print(f"  Category: {r.get('category_understood', '—')}")
        for p in r.get("validated_peers", []):
            print(f"  ✓ {p['domain']:25s} traffic={p['traffic']:>10,}  ({p['rationale'][:60]})")
        if r.get("skipped_invalid"):
            print(f"  Skipped: {r['skipped_invalid']}")
        print(f"  Units: {r.get('units_cost', 0)}")
