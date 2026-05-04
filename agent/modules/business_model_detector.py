"""
Detects whether a site is B2C ecommerce, B2B/SaaS, financial services, or other.
Gates the downstream scoring logic — different models get different thresholds.
"""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_B2C_URL_PATTERNS = re.compile(r"/(product|products|collections|shop|store|cart|checkout|category)/", re.I)
_B2B_URL_PATTERNS = re.compile(r"/(solutions?|pricing|demo|book-a-demo|contact-sales|case-stud|whitepaper|enterprise|platform|features)/", re.I)
_FINANCIAL_PATTERNS = re.compile(r"/(loan|mortgage|insurance|credit|policy|premium|emi|interest-rate|apply-now)/", re.I)

_B2C_CTA = re.compile(r"\b(add to cart|buy now|shop now|add to bag|order now)\b", re.I)
_B2B_CTA = re.compile(r"\b(book a demo|request demo|get a quote|contact sales|talk to sales|start free trial|schedule a call)\b", re.I)
_FIN_CTA = re.compile(r"\b(apply now|check eligibility|get a quote|calculate emi|apply for loan)\b", re.I)


@dataclass
class BusinessModel:
    primary:        str           # b2c_ecommerce | b2b_saas | financial | b2b_services | unknown
    confidence:     float         # 0-1
    signals:        dict          = field(default_factory=dict)
    schema_types:   list[str]     = field(default_factory=list)
    has_pricing:    bool          = False
    has_demo:       bool          = False

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "confidence": round(self.confidence, 2),
            "has_pricing": self.has_pricing,
            "has_demo": self.has_demo,
            "schema_types": self.schema_types,
            "signals": self.signals,
        }


def _fetch(url: str, timeout: int = 15) -> tuple[str, str] | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text, r.url
    except requests.RequestException:
        pass
    return None


def _schema_types(soup: BeautifulSoup) -> list[str]:
    types: list[str] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    t = item.get("@type")
                    if isinstance(t, str): types.append(t)
                    elif isinstance(t, list): types.extend(x for x in t if isinstance(x, str))
                    if "@graph" in item and isinstance(item["@graph"], list):
                        for g in item["@graph"]:
                            if isinstance(g, dict) and isinstance(g.get("@type"), str):
                                types.append(g["@type"])
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    return list(set(filter(None, types)))


def _check_path_exists(base: str, paths: list[str]) -> str | None:
    for p in paths:
        try:
            r = requests.head(urljoin(base, p), headers=_HEADERS, timeout=8, allow_redirects=True)
            if r.status_code == 200:
                return urljoin(base, p)
        except requests.RequestException:
            pass
    return None


def detect(url: str) -> BusinessModel:
    """Return a best-guess business model classification for a homepage URL."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.strip()

    fetched = _fetch(url)
    if not fetched:
        return BusinessModel("unknown", 0.0, {"error": "fetch_failed"})

    html, final_url = fetched
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True).lower()

    base = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"

    schemas = _schema_types(soup)
    schemas_lower = [s.lower() for s in schemas]

    has_product_schema = any(s in schemas_lower for s in ["product", "offer", "aggregateoffer"])
    has_org_schema = any(s in schemas_lower for s in ["organization", "softwareapplication", "service", "financialservice"])
    has_financial_schema = any(s in schemas_lower for s in ["financialservice", "financialproduct", "loanorcredit"])

    all_links = [a.get("href", "") for a in soup.find_all("a", href=True)]
    href_blob = " ".join(all_links).lower()

    b2c_url_hits = len(_B2C_URL_PATTERNS.findall(href_blob))
    b2b_url_hits = len(_B2B_URL_PATTERNS.findall(href_blob))
    fin_url_hits = len(_FINANCIAL_PATTERNS.findall(href_blob))

    b2c_cta = bool(_B2C_CTA.search(text))
    b2b_cta = bool(_B2B_CTA.search(text))
    fin_cta = bool(_FIN_CTA.search(text))

    pricing_url = _check_path_exists(base, ["/pricing", "/pricing/", "/plans"])
    demo_url    = _check_path_exists(base, ["/demo", "/book-a-demo", "/request-demo", "/contact-sales"])

    scores = {
        "b2c_ecommerce": (
            (3 if has_product_schema else 0)
            + min(b2c_url_hits, 10) * 0.5
            + (2 if b2c_cta else 0)
        ),
        "b2b_saas": (
            (2 if has_org_schema and not has_product_schema else 0)
            + min(b2b_url_hits, 10) * 0.5
            + (2 if b2b_cta else 0)
            + (2 if pricing_url else 0)
            + (2 if demo_url else 0)
        ),
        "financial": (
            (3 if has_financial_schema else 0)
            + min(fin_url_hits, 10) * 0.6
            + (2 if fin_cta else 0)
        ),
        "b2b_services": (
            (1 if has_org_schema and not has_product_schema else 0)
            + (1 if b2b_url_hits >= 2 else 0)
            + (1 if "case stud" in text or "our work" in text or "portfolio" in text else 0)
        ),
    }

    primary = max(scores, key=scores.get)
    top_score = scores[primary]
    runner_up = sorted(scores.values(), reverse=True)[1]
    confidence = 0.0 if top_score == 0 else min(1.0, (top_score - runner_up) / max(top_score, 1) + 0.3)
    if top_score < 2:
        primary = "unknown"

    return BusinessModel(
        primary=primary,
        confidence=confidence,
        schema_types=schemas,
        has_pricing=bool(pricing_url),
        has_demo=bool(demo_url),
        signals={
            "scores": {k: round(v, 1) for k, v in scores.items()},
            "b2c_url_hits": b2c_url_hits,
            "b2b_url_hits": b2b_url_hits,
            "fin_url_hits": fin_url_hits,
            "has_product_schema": has_product_schema,
            "has_org_schema": has_org_schema,
            "b2c_cta": b2c_cta,
            "b2b_cta": b2b_cta,
            "fin_cta": fin_cta,
        },
    )


if __name__ == "__main__":
    import sys
    for u in sys.argv[1:] or ["vinodcookware.com"]:
        result = detect(u)
        print(f"\n{u}")
        print(json.dumps(result.to_dict(), indent=2))
