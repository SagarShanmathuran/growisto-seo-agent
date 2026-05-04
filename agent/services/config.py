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
    """Lazy-load .env into os.environ. Idempotent."""
    global _DOT_ENV_LOADED
    if _DOT_ENV_LOADED:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
    _DOT_ENV_LOADED = True


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
    Returns the secret value for `key`, checking sources in priority order.
    Returns `default` (empty string) if not found in any source.
    """
    # 1. Streamlit Cloud's secrets manager (preferred in production)
    v = _from_streamlit_secrets(key)
    if v: return v

    # 2. Already in process env
    v = os.environ.get(key, "")
    if v: return v.strip()

    # 3. Lazy-load .env and check again
    _load_dotenv_once()
    return os.environ.get(key, default).strip() if os.environ.get(key) else default
