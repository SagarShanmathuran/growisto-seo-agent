"""
LLM-driven reasoning step that applies the SEO analyst's rules to a list of
raw competitor candidates and returns a tiered, relevance-ranked list.

This is the bridge between Ahrefs' "keyword overlap" signal (which surfaces
retailers + tangential brands) and the analyst's "business-context" judgment
(brand-vs-brand, transactional intent, 4x scope threshold, etc.).

Flow:
  Ahrefs candidates  →  reasoner  →  { tier_1, tier_2, off_target, reasoning }

The reasoner uses Gemini Flash (REST). Falls back to a deterministic
heuristic when the API is unavailable so the dashboard never blocks.
"""

import os
import json
import re
from pathlib import Path

import requests


_MODEL = "gemini-2.5-flash"
_MODEL_FALLBACKS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


from agent.services.config import get_secret


_PROMPT_TEMPLATE = """You are an experienced SEO analyst at Growisto helping pick the RIGHT competitors for a client SEO potential analysis. Your job is to filter a noisy list of candidate competitors (mostly from Ahrefs' organic-competitors API which surfaces by keyword overlap) down to the ones that genuinely fit the client's business and would yield a fair benchmark.

ANALYST RULES (apply rigorously):

1. B2B / SaaS / financial services / B2B services:
   - When competitor offers MULTIPLE services and only some overlap with the client's offering, treat them as PARTIAL fit (Tier 2). Only count their service-page-level traffic, not total domain traffic.
   - Focus on transactional / commercial-intent keywords (those that drive leads). Demote candidates whose traffic is mostly informational/blog.

2. B2C ecommerce — BRAND vs BRAND preference:
   - For brand client websites (Vinod, HyperX, Tarinika, ORRA), prefer other BRAND competitors (Tier 1).
   - DEMOTE multi-brand retailers (Croma, Reliance Digital, MD Computers, Lifestyle Stores, Shoppers Stop) and marketplaces (Amazon, Flipkart, Myntra, Ajio) when direct brand peers exist — they distort gap analysis.
   - If NO brand peers exist in the candidate list, then aggregators become an acceptable fallback (Tier 2).

3. Traffic-scope thresholds:
   - Ecommerce: high-relevance competitor needs ~4x or higher traffic than client (otherwise growth ceiling is too low to justify SEO investment).
   - B2B: total traffic matters less; instead value transactional keyword overlap and service-page traffic.

4. Domain-Rating sanity:
   - If competitor DR is 30+ points higher than client AND their traffic is 100x+, mark them as "aspirational" (Tier 2 at best — they're aspirational, not catchable in 12 months).

5. Reference / news / wiki / dictionary domains: ALWAYS off_target.

Return ONLY a JSON object with this exact structure:
{
  "top_3_picks": [
    {"domain": "...", "reason": "<1 sentence — why analyst should pull this CSV>", "confidence": "high|medium|low"},
    {"domain": "...", "reason": "...", "confidence": "..."},
    {"domain": "...", "reason": "...", "confidence": "..."}
  ],
  "alternates": [{"domain": "...", "reason": "<1 short sentence>"}, ...],
  "off_target": [{"domain": "...", "reason": "<1 short sentence>"}, ...],
  "summary": "<2-3 sentences explaining overall pick logic>",
  "warning": "<optional — if no good fits exist, say so and recommend analyst adds manual peers>"
}

CRITICAL:
- ALWAYS pick exactly 3 in top_3_picks (the analyst will pull CSVs for these — pick the best, even if compromised).
- If only 1 or 2 are truly relevant, fill the rest from second-tier with confidence="low" and warn in `warning`.
- Prefer brand-type domains over retailers when picking. If no brands exist, fall back to closest retailer.
- Within ecomm picks, prefer 4x–20x traffic ratio (sweet spot). Avoid 100x+ aspirational picks unless nothing else exists.

CLIENT CONTEXT:
{client_context}

NICHE / CATEGORY (auto-detected from sitemap):
{niche_hint}

CANDIDATE COMPETITORS (from Ahrefs, with classifier tags):
{candidates_json}
"""


def _score_candidate(c: dict, client: dict) -> tuple[float, str]:
    """Return (score, label) for one candidate. Higher score = better fit."""
    score = 0.0
    label_bits = []

    ctype = c.get("type", "unknown")
    type_score = {"brand": 100, "unknown": 50, "retailer": 0, "marketplace": -50, "reference": -1000}
    score += type_score.get(ctype, 0)

    client_traffic = client.get("traffic", 0)
    ctraffic = c.get("traffic", 0)
    if client_traffic > 0 and ctraffic > 0:
        ratio = ctraffic / client_traffic
        if 4.0 <= ratio <= 20.0:
            score += 50; label_bits.append(f"{ratio:.1f}× traffic — sweet spot")
        elif 1.5 <= ratio < 4.0:
            score += 20; label_bits.append(f"{ratio:.1f}× traffic — modest ceiling")
        elif 20.0 < ratio <= 100.0:
            score -= 10; label_bits.append(f"{ratio:.0f}× traffic — stretched")
        elif ratio > 100.0:
            score -= 50; label_bits.append(f"{ratio:.0f}× traffic — aspirational")
        else:
            score -= 30; label_bits.append(f"only {ratio:.1f}× — no growth ceiling")
    else:
        label_bits.append(f"{ctype.title()}")

    client_dr = client.get("domain_rating", 0) or 0
    cdr = c.get("domain_rating", 0) or 0
    dr_gap = cdr - client_dr
    if abs(dr_gap) <= 20: score += 20
    elif dr_gap > 40:     score -= 20

    label = " · ".join(label_bits) if label_bits else f"{ctype.title()}"
    return score, label


def _heuristic_fallback(client: dict, candidates: list[dict]) -> dict:
    """
    Deterministic fallback if Gemini unavailable.
    Picks top 3 by composite score, splits rest into alternates / off_target.
    """
    client_traffic = client.get("traffic", 0)
    is_ecomm = client.get("business_model", "") == "b2c_ecommerce"
    has_any_brand = any(c.get("type") == "brand" for c in candidates)

    # Score every candidate and split off-targets (reference, irrelevant)
    scored: list[tuple[float, dict, str]] = []
    off_target: list[dict] = []

    for c in candidates:
        ctype = c.get("type", "unknown")
        if ctype == "reference":
            off_target.append({"domain": c["domain"], "reason": "Reference / wiki / dictionary site"})
            continue
        score, label = _score_candidate(c, client)
        # Add brand-vs-aggregator note when applicable
        if ctype in ("retailer", "marketplace") and has_any_brand:
            label = f"{label} · {ctype} (brand peers exist)"
        scored.append((score, c, label))

    scored.sort(key=lambda x: -x[0])

    # Top 3 picks (highest scores)
    top_3 = []
    for s, c, label in scored[:3]:
        # Confidence: high if score >= 80, medium 30-80, low < 30
        conf = "high" if s >= 80 else ("medium" if s >= 30 else "low")
        top_3.append({"domain": c["domain"], "reason": label, "confidence": conf})

    alternates = [
        {"domain": c["domain"], "reason": label}
        for s, c, label in scored[3:]
    ]

    # Warning if even the top 3 are weak
    warning = ""
    pick_types = {c.get("type", "unknown") for s, c, _ in scored[:3]}
    only_retailers = pick_types and pick_types.issubset({"retailer", "marketplace"})

    if not scored:
        warning = "No usable candidates after filtering. Add competitors manually."
    elif scored[0][0] < 50:
        warning = ("None of the Ahrefs candidates are a strong fit. The agent picked "
                   "the best 3 of what's available — consider adding peer brands manually.")
    elif is_ecomm and only_retailers:
        warning = ("All 3 picks are retailers / marketplaces — Ahrefs didn't surface "
                   "any brand peers for this client. Strongly consider adding the actual "
                   "brand competitors manually (e.g., for gaming peripherals: Razer, "
                   "Logitech, SteelSeries).")
    elif scored[0][0] < 80:
        warning = ("Top picks are medium-confidence. Review the reasoning per pick "
                   "and add manual competitors if you have stronger peer brands in mind.")

    summary = (
        f"Picked top 3 of {len(scored)} usable candidates "
        f"({len(off_target)} dropped as off-target). "
        f"Brand peers available: {'yes' if has_any_brand else 'no'}."
    )
    return {
        "top_3_picks": top_3,
        "alternates":  alternates,
        "off_target":  off_target,
        "summary":     summary,
        "warning":     warning,
    }


def reason(
    *,
    client_url: str,
    client_name: str,
    business_model: str,
    client_traffic: int,
    client_keywords_total: int,
    client_dr: float | int = 0,
    niche_hint: str = "",
    candidates: list[dict],
    location: str = "India",
    verbose: bool = False,
) -> dict:
    """
    Returns:
      {
        "tier_1":     [{"domain": "...", "reason": "..."}, ...],
        "tier_2":     [{"domain": "...", "reason": "..."}, ...],
        "off_target": [{"domain": "...", "reason": "..."}, ...],
        "summary":    "...",
        "source":     "gemini" | "heuristic",
      }
    """
    client_ctx = {
        "url":             client_url,
        "name":            client_name,
        "business_model":  business_model,
        "traffic":         client_traffic,
        "keywords_total":  client_keywords_total,
        "domain_rating":   client_dr,
        "location":        location,
    }

    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        result = _heuristic_fallback(client_ctx, candidates)
        result["source"] = "heuristic"
        return result

    prompt = (_PROMPT_TEMPLATE
              .replace("{client_context}", json.dumps(client_ctx, indent=2))
              .replace("{niche_hint}",     niche_hint or "(unknown — infer from candidate keyword data and client URL)")
              .replace("{candidates_json}", json.dumps(candidates, indent=2)))

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
    }
    for model in _MODEL_FALLBACKS:
        try:
            r = requests.post(_ENDPOINT.format(model=model, key=api_key), json=body, timeout=45)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
                parsed = json.loads(text)
                parsed.setdefault("top_3_picks", [])
                parsed.setdefault("alternates",  [])
                parsed.setdefault("off_target",  [])
                parsed.setdefault("summary",     "")
                parsed.setdefault("warning",     "")
                parsed["source"] = "gemini"
                parsed["model"] = model
                if verbose: print(f"  [reasoner] picked via {model}")
                return parsed
            if r.status_code in (429, 503):
                if verbose: print(f"  [reasoner] {model}: HTTP {r.status_code} — trying next model")
                continue
            if verbose: print(f"  [reasoner] {model}: HTTP {r.status_code} — heuristic fallback")
            break
        except Exception as e:
            if verbose: print(f"  [reasoner] {model}: {type(e).__name__}: {str(e)[:80]}")
            continue
    # All models failed → heuristic fallback
    result = _heuristic_fallback(client_ctx, candidates)
    result["source"] = "heuristic"
    return result


if __name__ == "__main__":
    # Demo: HyperX scenario from the user's analysis
    sample = {
        "client_url":   "row.hyperx.com",
        "client_name":  "HyperX",
        "business_model": "b2c_ecommerce",
        "client_traffic": 4857,
        "client_keywords_total": 136,
        "client_dr":   45,
        "niche_hint":  "gaming peripherals (keyboards, headsets, mice)",
        "location":    "India",
        "candidates": [
            {"domain": "hp.com",          "type": "brand",       "keywords_common": 95, "traffic": 2821792, "domain_rating": 91},
            {"domain": "elitehubs.com",   "type": "retailer",    "keywords_common": 88, "traffic": 164353,  "domain_rating": 42},
            {"domain": "mdcomputers.in",  "type": "retailer",    "keywords_common": 52, "traffic": 306155,  "domain_rating": 46},
            {"domain": "rtings.com",      "type": "reference",   "keywords_common": 48, "traffic": 362199,  "domain_rating": 78},
            {"domain": "croma.com",       "type": "retailer",    "keywords_common": 38, "traffic": 5680217, "domain_rating": 73},
            {"domain": "computechstore.in","type": "retailer",   "keywords_common": 28, "traffic": 33862,   "domain_rating": 51},
            {"domain": "sclgaming.in",    "type": "retailer",    "keywords_common": 27, "traffic": 19481,   "domain_rating": 29},
            {"domain": "myitworld.com",   "type": "retailer",    "keywords_common": 23, "traffic": 18293,   "domain_rating": 18},
            {"domain": "pcstudio.in",     "type": "retailer",    "keywords_common": 19, "traffic": 26976,   "domain_rating": 40},
            {"domain": "reliancedigital.in","type": "retailer",  "keywords_common": 17, "traffic": 5919420, "domain_rating": 70},
        ],
        "verbose": True,
    }
    print(json.dumps(reason(**sample), indent=2))
