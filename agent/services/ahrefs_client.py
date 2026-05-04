"""
Direct Ahrefs API v3 client — used for high-quality competitor discovery.
Cheap (~210 units per call) compared to keyword/page exports.

Falls back gracefully if no token configured.

Auth: Bearer token from your Ahrefs subscription (same token the MCP uses).
Get it from: https://ahrefs.com/api/profile
"""

import os
from pathlib import Path

import requests


_BASE = "https://api.ahrefs.com/v3"
_USAGE_LOG = Path(__file__).resolve().parents[2] / "agent" / "data" / "ahrefs_usage.json"


from agent.services.config import get_secret


def _token() -> str | None:
    return get_secret("AHREFS_API_TOKEN") or None


def is_configured() -> bool:
    return _token() is not None


def _record_usage(endpoint: str, target: str, units: int) -> None:
    """Append a usage record to the local JSON log. Survives app restarts."""
    import json as _json
    from datetime import datetime
    _USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if _USAGE_LOG.exists():
        try:
            log = _json.loads(_USAGE_LOG.read_text())
        except (_json.JSONDecodeError, OSError):
            log = []
    log.append({
        "ts":       datetime.now().isoformat(timespec="seconds"),
        "endpoint": endpoint,
        "target":   target,
        "units":    units,
    })
    _USAGE_LOG.write_text(_json.dumps(log, indent=2))


def local_usage_summary() -> dict:
    """Read the local usage log → totals for this dashboard's consumption."""
    import json as _json
    from datetime import datetime, timedelta
    if not _USAGE_LOG.exists():
        return {"total_units": 0, "total_calls": 0, "last_30d_units": 0, "recent": []}

    try:
        log = _json.loads(_USAGE_LOG.read_text())
    except (_json.JSONDecodeError, OSError):
        return {"total_units": 0, "total_calls": 0, "last_30d_units": 0, "recent": []}

    total = sum(e.get("units", 0) for e in log)
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    last30 = sum(e.get("units", 0) for e in log if e.get("ts", "") >= cutoff)
    return {
        "total_units":    total,
        "total_calls":    len(log),
        "last_30d_units": last30,
        "recent":         log[-10:],
    }


def site_metrics(target: str, *, country: str = "in", date: str | None = None) -> dict:
    """
    Returns top-level SEO metrics for a single domain (used to show the client's
    own row alongside competitors). Cost: ~50 units.
    """
    token = _token()
    if not token:
        return {"error": "AHREFS_API_TOKEN not set"}

    if not date:
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d")

    target = target.replace("https://", "").replace("http://", "").strip("/").lower()
    target = target.replace("www.", "")

    try:
        r = requests.get(
            f"{_BASE}/site-explorer/metrics",
            params={"target": target, "country": country, "date": date, "mode": "subdomains"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        units = data.get("apiUsageCosts", {}).get("units-cost-total-actual", 0)
        _record_usage("metrics", target, units)
        m = data.get("metrics", {})
        return {
            "target":         target,
            "org_traffic":    m.get("org_traffic", 0),
            "org_keywords":   m.get("org_keywords", 0),
            "org_keywords_1_3": m.get("org_keywords_1_3", 0),
            "units_cost":     units,
        }
    except requests.RequestException as e:
        return {"error": str(e)}


def workspace_usage() -> dict:
    """Live Ahrefs workspace usage — calling this endpoint costs 0 units."""
    token = _token()
    if not token:
        return {"error": "AHREFS_API_TOKEN not set"}
    try:
        r = requests.get(
            f"{_BASE}/subscription-info/limits-and-usage",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:120]}"}
        data = r.json().get("limits_and_usage", {})
        used = data.get("units_usage_workspace", 0)
        limit = data.get("units_limit_workspace", 0)
        return {
            "subscription":        data.get("subscription"),
            "units_used":          used,
            "units_limit":         limit,
            "units_remaining":     max(0, limit - used),
            "pct_used":            round((used / limit * 100), 1) if limit else 0,
            "reset_date":          data.get("usage_reset_date"),
        }
    except requests.RequestException as e:
        return {"error": str(e)}


def organic_competitors(
    target: str,
    *,
    country: str = "in",
    limit: int = 15,
    date: str | None = None,
) -> dict:
    """
    Returns the top organic-search competitors for `target`, ranked by
    keyword overlap with the target site. This is the cleanest signal for
    "actual SEO competitors" — much better than SERP scraping.

    Cost: ~14 units per row, ~210 units for limit=15.

    Returns:
      {"competitors": [{"competitor_domain", "keywords_common", "keywords_competitor",
                        "domain_rating", "traffic"}, ...],
       "units_cost": int,
       "errors": [str]}
    """
    token = _token()
    if not token:
        return {"competitors": [], "units_cost": 0,
                "errors": ["AHREFS_API_TOKEN not set in .env"]}

    if not date:
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d")

    # Strip protocol if present (Ahrefs expects bare domain)
    target = target.replace("https://", "").replace("http://", "").strip("/").lower()
    target = target.replace("www.", "")

    params = {
        "select":   "competitor_domain,keywords_common,keywords_competitor,domain_rating,traffic",
        "target":   target,
        "country":  country,
        "date":     date,
        "mode":     "subdomains",
        "limit":    limit,
        "order_by": "keywords_common:desc",
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    try:
        r = requests.get(f"{_BASE}/site-explorer/organic-competitors",
                         params=params, headers=headers, timeout=30)
        if r.status_code == 401:
            return {"competitors": [], "units_cost": 0,
                    "errors": ["Ahrefs auth failed — check AHREFS_API_TOKEN"]}
        if r.status_code == 429:
            return {"competitors": [], "units_cost": 0,
                    "errors": ["Ahrefs rate limit hit — try again later"]}
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return {"competitors": [], "units_cost": 0,
                "errors": [f"Ahrefs request failed: {e}"]}

    units = data.get("apiUsageCosts", {}).get("units-cost-total-actual", 0)
    _record_usage("organic-competitors", target, units)
    return {
        "competitors": data.get("competitors", []),
        "units_cost":  units,
        "errors":      [],
    }


# Country code helpers ---------------------------------------------------------

_LOCATION_TO_COUNTRY = {
    "india":          "in",
    "united states":  "us",
    "united kingdom": "uk",
    "australia":      "au",
    "canada":         "ca",
    "uae":            "ae",
    "singapore":      "sg",
    "germany":        "de",
    "france":         "fr",
}


def country_code(location: str) -> str:
    return _LOCATION_TO_COUNTRY.get(location.lower().strip(), "us")


if __name__ == "__main__":
    import sys, json
    target = sys.argv[1] if len(sys.argv) > 1 else "tarinika.in"
    if not is_configured():
        print("AHREFS_API_TOKEN not set. Add it to .env to test.")
        sys.exit(1)
    result = organic_competitors(target, country="in", limit=10)
    print(json.dumps(result, indent=2))
