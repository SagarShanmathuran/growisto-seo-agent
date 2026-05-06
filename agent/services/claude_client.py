"""
Claude (Anthropic) REST client — used as the last-tier fallback when all
4 Gemini models are rate-limited.

Why: Gemini's free tier limits are aggressive (1500 requests/day per model).
Even with 4-model fallback, the agent occasionally hits a wall during busy
analysis sessions. Claude Haiku has no free-tier daily quota — pay-as-you-go,
extremely cheap (~$0.001 per analysis), so we use it only as the safety net.

Usage:
    from agent.services.claude_client import call_claude_json
    result = call_claude_json(prompt)   # returns parsed dict, or None on failure
"""

import json
import re
from typing import Optional

import requests

from agent.services.config import get_secret


_ENDPOINT = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5"
_API_VERSION = "2023-06-01"
_MAX_TOKENS = 4096


def is_configured() -> bool:
    return bool(get_secret("ANTHROPIC_API_KEY"))


def call_claude_json(
    prompt: str,
    *,
    model: str = _MODEL,
    max_tokens: int = _MAX_TOKENS,
    temperature: float = 0.3,
    timeout: int = 45,
    verbose: bool = False,
) -> Optional[dict]:
    """
    Send `prompt` to Claude, expect a JSON object back. Returns parsed dict
    on success, None on any failure (auth error, parse error, rate limit, etc).
    Caller is responsible for handling None.

    The prompt should already include any "respond with ONLY a JSON object"
    instructions from the caller — Claude is good at JSON output when asked.
    """
    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        if verbose: print("  [claude] no ANTHROPIC_API_KEY — skipping")
        return None

    body = {
        "model":       model,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "messages":    [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": _API_VERSION,
        "content-type":      "application/json",
    }

    try:
        r = requests.post(_ENDPOINT, json=body, headers=headers, timeout=timeout)
        if r.status_code != 200:
            if verbose: print(f"  [claude] HTTP {r.status_code}: {r.text[:120]}")
            return None
        data = r.json()
        # Claude returns {"content": [{"type": "text", "text": "..."}], ...}
        text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        text = "\n".join(text_blocks).strip()
        # Strip markdown code-fence if present
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        if verbose: print(f"  [claude] {model} responded ({len(text)} chars)")
        return parsed
    except json.JSONDecodeError as e:
        if verbose: print(f"  [claude] JSON parse failed: {e}")
        return None
    except Exception as e:
        if verbose: print(f"  [claude] {type(e).__name__}: {str(e)[:120]}")
        return None


if __name__ == "__main__":
    # Smoke test
    if not is_configured():
        print("ANTHROPIC_API_KEY not configured. Add it to .env to test.")
        raise SystemExit(1)
    out = call_claude_json(
        'Reply with this JSON: {"status": "ok", "model": "claude-haiku-4-5"}',
        verbose=True,
    )
    print("Response:", out)
