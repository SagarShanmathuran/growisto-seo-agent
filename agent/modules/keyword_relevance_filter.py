"""
LLM-driven keyword relevance filter.

Replaces the token-overlap heuristic in gap_analyzer.py for the central question:
"Is this competitor keyword something the client could realistically rank for
given what they actually sell?"

Token heuristics don't generalize across verticals — there's no finite list of
"generic vertical tokens" that covers cat-litter, jewelry, SaaS, finance, fashion,
B2B services, etc. without breaking on the next test case.

Instead: send the client's top-20 keywords (as scope evidence) + a list of
candidate gap keywords to Gemini in ONE call, get back a JSON map of
{keyword: in_scope_boolean}. One LLM call per analysis.

Falls back to the token heuristic (gap_analyzer._is_relevant_to_client) when
Gemini is unavailable.

Cost: 1 Gemini call (free on free tier with our model fallback chain).
"""

import json
import re
import time
from pathlib import Path

import requests

from agent.services.config import get_secret


_MODELS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


_PROMPT = """You are an SEO analyst at Growisto. The agent is filtering competitor gap keywords for an SEO analysis.

A keyword is RELEVANT only if a customer searching for it would expect to land on a page from a website that sells the same products/services as the client. Informational keywords, products outside the client's catalog, or different customer segments are NOT relevant.

CLIENT URL: {client_url}
CLIENT NAME: {client_name}
BUSINESS MODEL: {business_model}
NICHE HINT: {niche_hint}

CLIENT'S TOP-RANKED KEYWORDS (these define what the client actually sells):
{client_keywords}

CANDIDATE GAP KEYWORDS (each ranks well for at least one competitor, not for the client — decide if each is in client's scope):
{candidates}

Return ONLY a JSON object with this exact structure:
{
  "scope_description": "<1-sentence description of what the client actually sells, inferred from their ranked kws>",
  "in_scope_keywords": ["kw1", "kw2", ...],
  "out_of_scope_keywords": ["kw3", "kw4", ...],
  "out_of_scope_reasons": {"kw3": "<reason>", "kw4": "<reason>"}
}

Strict rules:
- Every candidate must appear in EXACTLY ONE of in_scope_keywords or out_of_scope_keywords.
- For out_of_scope_keywords, include a 1-line reason in out_of_scope_reasons.
- Be strict: if uncertain, mark out_of_scope. The client should only invest SEO effort on keywords clearly in their catalog scope.
- Examples of out-of-scope reasons: "informational, not transactional", "different product category client doesn't sell", "different customer segment", "competitor brand name".
""".strip()


def _build_prompt(*, client_url, client_name, business_model, niche_hint,
                  client_keywords: list[str], candidates: list[str]) -> str:
    # Bullet-list the client kws (volume not needed — just the kw string is enough scope)
    client_kw_block = "\n".join(f"- {k}" for k in client_keywords[:25])
    cand_block = "\n".join(f"- {k}" for k in candidates)
    return (_PROMPT
            .replace("{client_url}",     client_url)
            .replace("{client_name}",    client_name)
            .replace("{business_model}", business_model or "unknown")
            .replace("{niche_hint}",     niche_hint or "(unknown)")
            .replace("{client_keywords}", client_kw_block)
            .replace("{candidates}",     cand_block))


def classify_relevance(
    *,
    client_url: str,
    client_name: str,
    business_model: str,
    niche_hint: str,
    client_top_keywords: list[str],
    candidate_keywords: list[str],
    verbose: bool = False,
) -> dict:
    """
    Returns:
      {
        "scope_description": "...",
        "in_scope": set[str],
        "out_of_scope": set[str],
        "reasons": dict[kw, str],
        "source": "gemini" | "skipped",
      }

    On failure: empty in_scope / out_of_scope sets, source="skipped" — caller
    should fall back to its own heuristic.
    """
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key or not candidate_keywords:
        return {"scope_description": "", "in_scope": set(), "out_of_scope": set(),
                "reasons": {}, "source": "skipped",
                "skip_reason": "no GEMINI_API_KEY" if not api_key else "no candidates"}

    # Cap candidates per call — Gemini handles ~100-150 keywords easily, larger payloads fail
    candidates = candidate_keywords[:120]

    prompt = _build_prompt(
        client_url=client_url, client_name=client_name,
        business_model=business_model, niche_hint=niche_hint,
        client_keywords=client_top_keywords, candidates=candidates,
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }

    last_status = None
    last_error = ""
    for model in _MODELS:
        try:
            r = requests.post(_ENDPOINT.format(model=model, key=api_key), json=body, timeout=60)
            last_status = r.status_code
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
                parsed = json.loads(text)
                in_scope = {str(k).lower().strip() for k in parsed.get("in_scope_keywords", [])}
                out_scope = {str(k).lower().strip() for k in parsed.get("out_of_scope_keywords", [])}
                reasons = {str(k).lower().strip(): str(v) for k, v in parsed.get("out_of_scope_reasons", {}).items()}
                if verbose:
                    print(f"  [kw-relevance] {len(in_scope)} in-scope, {len(out_scope)} out-of-scope via {model}")
                return {
                    "scope_description": parsed.get("scope_description", ""),
                    "in_scope": in_scope,
                    "out_of_scope": out_scope,
                    "reasons": reasons,
                    "source": "gemini",
                    "model": model,
                }
            if r.status_code in (429, 503):
                if verbose: print(f"  [kw-relevance] {model}: HTTP {r.status_code} — trying next")
                time.sleep(0.5)
                continue
            last_error = f"HTTP {r.status_code}: {r.text[:120]}"
            break
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:120]}"
            if verbose: print(f"  [kw-relevance] {model}: {last_error}")
            continue

    return {
        "scope_description": "",
        "in_scope":          set(),
        "out_of_scope":      set(),
        "reasons":           {},
        "source":            "skipped",
        "skip_reason":       f"Gemini unavailable (last: {last_status or last_error or 'unknown'})",
    }


if __name__ == "__main__":
    # Smoke test — Catalystpet (cat litter brand)
    out = classify_relevance(
        client_url="catalystpet.com",
        client_name="Catalyst Pet",
        business_model="b2c_ecommerce",
        niche_hint="natural cat litter, biodegradable pellet litter",
        client_top_keywords=[
            "catalyst cat litter", "natural cat litter", "biodegradable cat litter",
            "pellet cat litter", "kitty litter", "wood pellet cat litter",
            "best non-clumping litter", "tofu cat litter",
        ],
        candidate_keywords=[
            "norwegian forest cat", "orange cat", "burmese cat",
            "cat tree", "litter box", "cat litter", "kitty litter scoop",
            "cat furniture", "cat food", "catnip toys", "best cat litter",
            "tofu cat litter", "wood pellet litter",
        ],
        verbose=True,
    )
    print(f"\nScope: {out['scope_description']}")
    print(f"\nIN scope ({len(out['in_scope'])}):")
    for kw in sorted(out["in_scope"]): print(f"  ✓ {kw}")
    print(f"\nOUT of scope ({len(out['out_of_scope'])}):")
    for kw in sorted(out["out_of_scope"]):
        print(f"  ✗ {kw}  —  {out['reasons'].get(kw, '')}")
