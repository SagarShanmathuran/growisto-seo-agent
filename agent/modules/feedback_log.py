"""
Persistent analyst feedback log — captures what the agent got right/wrong
across sites, so we can systematically improve based on real usage.

Storage: agent/data/analyst_feedback.json (newline-delimited JSON entries)

Each entry types:
  - "competitor_rating": did Ahrefs surface useful competitors?
  - "competitor_added":  manual additions the analyst made
  - "competitor_dismissed": Ahrefs picks the analyst rejected
  - "analysis_verdict":  final H/M/L decision + analyst notes
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG_PATH = Path(__file__).resolve().parents[2] / "agent" / "data" / "analyst_feedback.json"


def _load() -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    try:
        return json.loads(_LOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list[dict]) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOG_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def record(
    *,
    kind: str,
    client_url: str,
    client_name: str = "",
    niche: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    """Append a feedback record."""
    entries = _load()
    entries.append({
        "ts":          datetime.now().isoformat(timespec="seconds"),
        "kind":        kind,
        "client_url":  client_url,
        "client_name": client_name,
        "niche":       niche,
        **(payload or {}),
    })
    _save(entries)


def all_entries() -> list[dict]:
    return _load()


def by_kind(kind: str) -> list[dict]:
    return [e for e in _load() if e.get("kind") == kind]


def summary() -> dict:
    entries = _load()
    if not entries:
        return {"total": 0, "kinds": {}, "sites_analyzed": 0}

    kinds: dict[str, int] = {}
    sites: set[str] = set()
    helpful_count = 0
    not_helpful_count = 0
    manually_added: list[str] = []
    dismissed: list[str] = []

    for e in entries:
        kinds[e.get("kind", "unknown")] = kinds.get(e.get("kind", "unknown"), 0) + 1
        if e.get("client_url"):
            sites.add(e["client_url"])
        if e.get("kind") == "competitor_rating":
            if e.get("helpful") is True:  helpful_count += 1
            if e.get("helpful") is False: not_helpful_count += 1
        if e.get("kind") == "competitor_added":
            manually_added.append(e.get("domain", ""))
        if e.get("kind") == "competitor_dismissed":
            dismissed.append(e.get("domain", ""))

    return {
        "total":              len(entries),
        "kinds":              kinds,
        "sites_analyzed":     len(sites),
        "ahrefs_helpful":     helpful_count,
        "ahrefs_not_helpful": not_helpful_count,
        "manually_added":     manually_added,
        "dismissed":          dismissed,
    }
