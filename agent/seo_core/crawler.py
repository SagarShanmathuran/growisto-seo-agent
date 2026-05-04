"""Web crawling module — extracts 20+ SEO signals from a website."""

import time
import json
from urllib.parse import urljoin, urlparse
from typing import Any

import requests
from bs4 import BeautifulSoup


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


class WebCrawler:
    """Crawls a website's homepage and supplementary URLs to collect SEO signals."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.timeout = cfg.get("timeout", 15)

    # ── public ────────────────────────────────────────────────────────────────

    def crawl(self, url: str) -> dict[str, Any]:
        """
        Crawl *url* and return a flat dict of SEO signals.
        Never raises — errors are captured in the ``error`` key.
        """
        url = self._normalise(url)
        domain = urlparse(url).netloc

        try:
            t0 = time.perf_counter()
            resp = requests.get(url, headers=_HEADERS, timeout=self.timeout,
                                allow_redirects=True)
            load_time = round(time.perf_counter() - t0, 3)
        except requests.RequestException as exc:
            return {"url": url, "error": str(exc)}

        soup = BeautifulSoup(resp.text, "lxml")

        data: dict[str, Any] = {
            "url": url,
            "final_url": resp.url,
            "status_code": resp.status_code,
            "load_time_s": load_time,
            "redirect_count": len(resp.history),
            "uses_https": resp.url.startswith("https://"),
            "page_size_kb": round(len(resp.content) / 1024, 1),
        }

        data.update(self._on_page(soup))
        data.update(self._robots(domain, url))
        data.update(self._sitemap(domain, url))

        return data

    # ── on-page extraction ────────────────────────────────────────────────────

    def _on_page(self, soup: BeautifulSoup) -> dict[str, Any]:
        title       = self._text(soup.find("title"))
        meta_desc   = self._attr(soup.find("meta", attrs={"name": "description"}), "content")
        meta_keys   = self._attr(soup.find("meta", attrs={"name": "keywords"}), "content")
        canonical   = self._attr(soup.find("link", attrs={"rel": "canonical"}), "href")
        viewport    = bool(soup.find("meta", attrs={"name": "viewport"}))
        hreflang    = len(soup.find_all("link", attrs={"rel": "alternate", "hreflang": True}))

        h1s = [h.get_text(strip=True) for h in soup.find_all("h1")]
        h2s = [h.get_text(strip=True) for h in soup.find_all("h2")]
        h3s = [h.get_text(strip=True) for h in soup.find_all("h3")]

        imgs         = soup.find_all("img")
        imgs_no_alt  = [i for i in imgs if not i.get("alt", "").strip()]

        all_links    = soup.find_all("a", href=True)
        ext_links    = [l for l in all_links if l["href"].startswith("http")]

        body_text    = soup.get_text(" ", strip=True)
        word_count   = len(body_text.split())

        og_tags      = {t["property"]: t.get("content", "")
                        for t in soup.find_all("meta", property=True)
                        if t["property"].startswith("og:")}
        twitter_tags = {t.get("name", t.get("property", "")): t.get("content", "")
                        for t in soup.find_all("meta")
                        if (t.get("name") or t.get("property", "")).startswith("twitter:")}

        schema_types = self._schema_types(soup)

        return {
            # Title
            "title":            title,
            "title_len":        len(title) if title else 0,
            # Meta description
            "meta_desc":        meta_desc,
            "meta_desc_len":    len(meta_desc) if meta_desc else 0,
            "meta_keywords":    meta_keys,
            # Canonical / hreflang
            "canonical":        canonical,
            "hreflang_count":   hreflang,
            # Headings
            "h1_tags":          h1s,
            "h1_count":         len(h1s),
            "h2_count":         len(h2s),
            "h3_count":         len(h3s),
            # Images
            "img_count":        len(imgs),
            "img_no_alt":       len(imgs_no_alt),
            # Links
            "link_total":       len(all_links),
            "link_external":    len(ext_links),
            # Content
            "word_count":       word_count,
            # Mobile / UX
            "has_viewport":     viewport,
            # Social
            "og_tags":          og_tags,
            "has_og":           bool(og_tags),
            "twitter_tags":     twitter_tags,
            "has_twitter_card": bool(twitter_tags),
            # Structured data
            "schema_types":     schema_types,
            "has_schema":       bool(schema_types),
        }

    # ── robots.txt ────────────────────────────────────────────────────────────

    def _robots(self, domain: str, base_url: str) -> dict[str, Any]:
        robots_url = f"{urlparse(base_url).scheme}://{domain}/robots.txt"
        try:
            r = requests.get(robots_url, headers=_HEADERS,
                             timeout=self.timeout, allow_redirects=True)
            exists = r.status_code == 200
            has_sitemap_ref = exists and "sitemap:" in r.text.lower()
        except requests.RequestException:
            exists, has_sitemap_ref = False, False
        return {
            "robots_txt_exists":   exists,
            "robots_sitemap_ref":  has_sitemap_ref,
        }

    # ── sitemap.xml ───────────────────────────────────────────────────────────

    def _sitemap(self, domain: str, base_url: str) -> dict[str, Any]:
        scheme = urlparse(base_url).scheme
        for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap.xml.gz"):
            try:
                r = requests.get(f"{scheme}://{domain}{path}", headers=_HEADERS,
                                 timeout=self.timeout, allow_redirects=True)
                if r.status_code == 200:
                    return {"sitemap_exists": True, "sitemap_url": r.url}
            except requests.RequestException:
                pass
        return {"sitemap_exists": False, "sitemap_url": None}

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _text(tag) -> str | None:
        return tag.get_text(strip=True) if tag else None

    @staticmethod
    def _attr(tag, attr: str) -> str | None:
        return tag.get(attr) if tag else None

    @staticmethod
    def _normalise(url: str) -> str:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return url

    @staticmethod
    def _schema_types(soup: BeautifulSoup) -> list[str]:
        types: list[str] = []
        # JSON-LD
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                if isinstance(data, dict) and "@type" in data:
                    types.append(data["@type"])
                elif isinstance(data, list):
                    types.extend(d.get("@type", "") for d in data if isinstance(d, dict))
            except (json.JSONDecodeError, AttributeError):
                pass
        # Microdata
        for tag in soup.find_all(attrs={"itemtype": True}):
            t = tag["itemtype"].split("/")[-1]
            if t:
                types.append(t)
        return list(set(filter(None, types)))
