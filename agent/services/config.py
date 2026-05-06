"""
Centralized secret/config loader.

Resolution order:
  1. Streamlit's st.secrets (production — Streamlit Cloud secrets manager)
  2. Process env vars
  3. .env file (local dev)

Modules that need keys should call get_secret("GEMINI_API_KEY") instead of
reading os.environ directly. That way the same code works both locally and
in production without any branching.
"""

import os
from pathlib import Path
from typing import Optional


_DOT_ENV_LOADED = False


def _load_dotenv_once() -> None:
    """Lazy-load .env into os.environ. Idempotent.

    Also normalizes loose key formats: 'Claude API Key' → 'CLAUDE_API_KEY'
    (spaces → underscores, uppercased) so tolerant for hand-edited .env files.
    """
    global _DOT_ENV_LOADED
    if _DOT_ENV_LOADED:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                k_clean = k.strip()
                v_clean = v.strip()
                os.environ[k_clean] = v_clean
                # Also store a normalized form for tolerant lookup
                normalized = k_clean.replace(" ", "_").replace("-", "_").upper()
                if normalized != k_clean:
                    os.environ[normalized] = v_clean
    _DOT_ENV_LOADED = True


# Aliases — when callers ask for one canonical name, we also check common variants
_KEY_ALIASES: dict[str, list[str]] = {
    "ANTHROPIC_API_KEY": ["CLAUDE_API_KEY", "CLAUDE_KEY"],
    "GEMINI_API_KEY":    ["GOOGLE_GEMINI_KEY", "GOOGLE_API_KEY"],
    "AHREFS_API_TOKEN":  ["AHREFS_TOKEN", "AHREFS_KEY"],
    "SEARCHAPI_KEY":     ["SEARCH_API_KEY", "SERPAPI_KEY"],
}


def _from_streamlit_secrets(key: str) -> Optional[str]:
    """Try st.secrets — only works when running under Streamlit."""
    try:
        import streamlit as st
        v = st.secrets.get(key, None)
        if v: return str(v).strip()
    except Exception:
        pass
    return None


def get_secret(key: str, default: str = "") -> str:
    """
    Returns the secret value for `key`, checking sources in priority order
    and tolerating common aliases (ANTHROPIC_API_KEY ↔ CLAUDE_API_KEY etc.).
    Returns `default` (empty string) if not found in any source.
    """
    candidates = [key] + _KEY_ALIASES.get(key, [])
    for candidate in candidates:
        # 1. Streamlit Cloud's secrets manager (preferred in production)
        v = _from_streamlit_secrets(candidate)
        if v: return v
        # 2. Already in process env
        v = os.environ.get(candidate, "")
        if v: return v.strip()

    # 3. Lazy-load .env and re-try all candidates (covers hand-edited files
    # with messy formatting like "Claude API Key" → CLAUDE_API_KEY)
    _load_dotenv_once()
    for candidate in candidates:
        v = os.environ.get(candidate, "")
        if v: return v.strip()

    return default
