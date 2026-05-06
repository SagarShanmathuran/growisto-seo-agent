"""
Gemini Flash via REST API (no SDK — avoids cryptography DLL issues on Windows).
Produces the top-line H/M/L verdict + 1-line summary.
Falls back to a deterministic template if the API is unavailable.
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


def _load_env():  # back-compat shim
    pass


_FEW_SHOT = """You are an SEO consultant at Growisto. Score websites for SEO outreach potential as HIGH, MEDIUM, or LOW.

Reference examples (Growisto's actual writing style):

Vinod Cookware (35K non-brand traffic, competitors 4-7x larger, 25 high-value gap keywords)
→ HIGH. Traffic Potential: Vinod is getting 35K non-brand traffic, while competitors like Milton (262K), Borosil (219K) are 4-7x larger. Keyword Ranking: Vinod doesn't rank for core terms like water bottle, mixer grinder, gas stove where competitors rank top 10. Scope: 25 high-value gap keywords with 1.6M monthly volume.

Aviva India (2.9K non-brand traffic, B2B insurance)
→ HIGH. Traffic Potential: Aviva India currently gets 2.9K non-brand traffic, while competitors like Tata AIA achieve 220K and Edelweiss Life 22K, indicating significant growth opportunities.

Mayorga Coffee (low AOV, blog-funnel based, B2C subscription)
→ MEDIUM. 96% non-brand traffic comes from blogs. Some scope to expand transactional category pages for subscription growth.

Soch (143K traffic, already mature SEO execution)
→ LOW. Soch is getting 143K non-brand traffic but existing pages are well optimized. Mature execution. Limited room to scale further.

Rules:
- B2B / financial / SaaS sites can be HIGH even with <5K traffic if AOV/contract value is high
- B2C ecommerce with thin catalog (<50 pages) and low AOV → likely LOW
- If client already ranks top 10 for most core keywords → LOW (limited upside)
- If competitors are losing traffic → favorable timing, lean toward HIGHER tier

Now write a verdict for the following client. Output ONLY a JSON object with two fields:
{"potential": "HIGH|MEDIUM|LOW", "summary": "<2-3 sentence verdict in Growisto's style — start with Traffic Potential or Keyword Ranking framing>"}
"""


def _template_fallback(data: dict) -> dict:
    ratio = data.get("traffic_ratio", 0)
    gap_vol = data.get("gap_total_volume", 0)
    is_b2b = data.get("business_model", "").startswith("b2b") or data.get("business_model") == "financial"
    page_delta = data.get("page_count_delta", 0)
    notes = data.get("notes", [])

    if is_b2b:
        if ratio < 0.3 and gap_vol >= 50_000:
            potential = "HIGH"
        elif ratio < 0.7:
            potential = "MEDIUM"
        else:
            potential = "LOW"
    else:
        if ratio < 0.3 and gap_vol >= 200_000 and page_delta > 50:
            potential = "HIGH"
        elif ratio < 0.7 and gap_vol >= 50_000:
            potential = "MEDIUM"
        else:
            potential = "LOW"

    bits = [f"Traffic Potential: client gets {int(data.get('client_traffic',0)):,} non-brand traffic vs competitor avg {int(data.get('avg_comp_traffic',0)):,}."]
    if gap_vol:
        bits.append(f"Identified {len(data.get('top_gap_keywords',[]))} high-value gap keywords representing {gap_vol:,} monthly search volume.")
    if notes:
        bits.append(notes[0])
    return {"potential": potential, "summary": " ".join(bits)}


def synthesize_verdict(data: dict, *, verbose: bool = False) -> dict:
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        if verbose: print("  [gemini] no key — using template fallback")
        return _template_fallback(data)

    prompt = _FEW_SHOT + "\n\nCLIENT DATA:\n" + json.dumps(data, indent=2, default=str)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
    }
    for model in _MODEL_FALLBACKS:
        try:
            r = requests.post(_ENDPOINT.format(model=model, key=api_key), json=body, timeout=30)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
                parsed = json.loads(text)
                if "potential" in parsed and "summary" in parsed:
                    parsed["potential"] = parsed["potential"].upper()
                    if verbose: print(f"  [gemini] verdict via {model}")
                    return parsed
            if r.status_code in (429, 503):
                if verbose: print(f"  [gemini] {model}: HTTP {r.status_code} — trying next")
                continue
            break
        except Exception as e:
            if verbose: print(f"  [gemini] {model}: {type(e).__name__} — trying next")
            continue
    # All Gemini models exhausted — try Claude Haiku before template fallback
    from agent.services.claude_client import call_claude_json, is_configured as _claude_ok
    if _claude_ok():
        if verbose: print("  [gemini] all Gemini models failed — trying Claude Haiku")
        parsed = call_claude_json(prompt, verbose=verbose)
        if parsed and "potential" in parsed and "summary" in parsed:
            parsed["potential"] = parsed["potential"].upper()
            if verbose: print("  [gemini] verdict via Claude Haiku")
            return parsed

    if verbose: print("  [gemini] all LLMs failed — using template fallback")
    return _template_fallback(data)


if __name__ == "__main__":
    sample = {
        "client_name": "Vinod Cookware",
        "client_traffic": 35123,
        "avg_comp_traffic": 210311,
        "traffic_ratio": 0.167,
        "gap_total_volume": 1757000,
        "top_gap_keywords": [
            ("water bottle", 196000, "Milton", 2),
            ("air fryer", 260000, "TTK Prestige", 6),
            ("mixer grinder", 120000, "Borosil", 3),
        ],
        "page_count_delta": 244,
        "business_model": "b2c_ecommerce",
        "notes": [
            "Client gets only 17% of avg competitor traffic — large gap",
            "Massive gap-keyword opportunity: 1,757,000 monthly search volume across 30 keywords",
            "Competitors losing traffic: Borosil, TTK Prestige — favorable timing",
        ],
    }
    print(json.dumps(synthesize_verdict(sample, verbose=True), indent=2))
