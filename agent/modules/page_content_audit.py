"""
On-page content audit for the short report.

Goes beyond the basic crawler — specifically inspects what an SEO analyst checks
manually when assessing a category/product page:
  - Above-the-fold visible content (real text vs just product tiles)
  - Footer content depth (especially important for ecomm category pages)
  - H1/H2 heading structure quality
  - Schema markup presence (Product, BreadcrumbList, FAQPage)
  - Content word count split between body and footer
  - Internal-link density
"""

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _find_footer_node(soup: BeautifulSoup) -> Tag | None:
    """Locate the footer element. <footer> is the standard, but many sites use
    classes like 'site-footer' or 'page-footer'."""
    candidates = (
        soup.find("footer"),
        soup.find(attrs={"role": "contentinfo"}),
        soup.find(class_=re.compile(r"\b(site-?footer|page-?footer|main-?footer)\b", re.I)),
        soup.find(id=re.compile(r"\b(site-?footer|page-?footer|footer)\b", re.I)),
    )
    return next((c for c in candidates if c is not None), None)


def _find_main_content_node(soup: BeautifulSoup) -> Tag:
    """Locate the main content area (excluding header, nav, footer)."""
    candidates = (
        soup.find("main"),
        soup.find(attrs={"role": "main"}),
        soup.find("article"),
        soup.find(id=re.compile(r"\b(main-?content|content|primary)\b", re.I)),
        soup.find(class_=re.compile(r"\b(main-?content|page-?content)\b", re.I)),
    )
    return next((c for c in candidates if c is not None), soup.body or soup)


def _strip_clutter(node: Tag) -> str:
    """Pull text out, removing navigation, scripts, styles."""
    if node is None: return ""
    for s in node.find_all(["script", "style", "noscript"]):
        s.decompose()
    return node.get_text(" ", strip=True)


def audit(url: str, *, timeout: int = 20) -> dict:
    """
    Returns:
      {
        "url":                    final URL crawled
        "status":                 HTTP status
        "title", "title_len":     page title metadata
        "meta_desc", "meta_desc_len"
        "h1", "h1_count":         all H1s + count
        "h2_count", "h3_count"
        "above_fold_word_count":  word count in main content area
        "footer_word_count":      word count inside <footer>
        "has_substantive_footer": True if footer has > 100 words (good signal for ecomm)
        "schema_types":           list of detected JSON-LD @types
        "has_product_schema":     bool
        "has_breadcrumb_schema":  bool
        "has_faq_schema":         bool
        "img_count", "img_no_alt"
        "internal_link_count":    # of links to same domain
        "external_link_count":    # of links to other domains
        "issues":                 list of human-readable findings
      }
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.strip()

    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        return {"url": url, "error": str(e), "issues": ["Crawl failed: " + str(e)]}

    soup = BeautifulSoup(r.text, "lxml")
    final_url = r.url
    parsed = urlparse(final_url)
    base_host = parsed.netloc.replace("www.", "").lower()

    # ── Meta ──
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    md_tag = soup.find("meta", attrs={"name": "description"})
    meta_desc = md_tag.get("content", "").strip() if md_tag else ""

    # ── Headings ──
    h1s = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
    h2_count = len(soup.find_all("h2"))
    h3_count = len(soup.find_all("h3"))

    # ── Body / footer split ──
    main_node   = _find_main_content_node(soup)
    footer_node = _find_footer_node(soup)
    if footer_node and main_node and footer_node in main_node.descendants:
        # If footer was inside main, exclude it from main's text
        main_clone = BeautifulSoup(str(main_node), "lxml")
        for f in main_clone.find_all("footer"):
            f.decompose()
        main_text = _strip_clutter(main_clone)
    else:
        main_text = _strip_clutter(main_node)
    footer_text = _strip_clutter(footer_node) if footer_node else ""

    above_fold_wc = len(main_text.split())
    footer_wc     = len(footer_text.split())

    # ── Schema ──
    schema_types: list[str] = []
    import json
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict):
                    t = it.get("@type")
                    if isinstance(t, str): schema_types.append(t)
                    elif isinstance(t, list): schema_types.extend(x for x in t if isinstance(x, str))
                    if "@graph" in it and isinstance(it["@graph"], list):
                        for g in it["@graph"]:
                            if isinstance(g, dict) and isinstance(g.get("@type"), str):
                                schema_types.append(g["@type"])
        except (json.JSONDecodeError, AttributeError):
            pass
    schema_types = sorted(set(filter(None, schema_types)))
    schema_lower = [s.lower() for s in schema_types]

    # ── Images ──
    imgs = soup.find_all("img")
    img_no_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())

    # ── Links ──
    internal = external = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("/", "#")):
            internal += 1
        elif href.startswith(("http://", "https://")):
            host = urlparse(href).netloc.replace("www.", "").lower()
            if host == base_host:
                internal += 1
            else:
                external += 1

    has_product   = any("product" in s for s in schema_lower)
    has_breadcrumb = any("breadcrumb" in s for s in schema_lower)
    has_faq       = any("faq" in s for s in schema_lower)

    # ── Issues / findings (analyst-style) ──
    issues: list[str] = []
    if not title:                            issues.append("Page title missing")
    elif len(title) < 30 or len(title) > 70: issues.append(f"Title is {len(title)} chars (ideal 30–70)")
    if not meta_desc:                        issues.append("Meta description missing")
    elif len(meta_desc) < 100 or len(meta_desc) > 170:
                                              issues.append(f"Meta description is {len(meta_desc)} chars (ideal 100–170)")
    if len(h1s) == 0:                        issues.append("No H1 heading found")
    elif len(h1s) > 1:                       issues.append(f"{len(h1s)} H1 tags (should be exactly 1)")
    if h2_count < 2:                         issues.append(f"Only {h2_count} H2 heading(s) — page lacks structure")
    if above_fold_wc < 300:                  issues.append(f"Main content has only {above_fold_wc} words — too thin (aim 500+ for category pages)")
    if footer_wc < 50:                       issues.append(f"Footer has only {footer_wc} words — missing footer content (recommended for ecomm)")
    if not has_breadcrumb:                   issues.append("No BreadcrumbList schema — adds rich-result eligibility")
    if not has_product and any(seg in parsed.path for seg in ("/product", "/products")):
                                              issues.append("Product page without Product schema")
    if img_no_alt > 5:                       issues.append(f"{img_no_alt} images missing alt text")
    if external > internal * 2 and external > 20:
                                              issues.append("External links outnumber internal — review link structure")

    return {
        "url":                    final_url,
        "status":                 r.status_code,
        "title":                  title,
        "title_len":              len(title),
        "meta_desc":              meta_desc[:200],
        "meta_desc_len":          len(meta_desc),
        "h1":                     h1s[0] if h1s else "",
        "h1_count":               len(h1s),
        "h2_count":               h2_count,
        "h3_count":               h3_count,
        "above_fold_word_count":  above_fold_wc,
        "footer_word_count":      footer_wc,
        "has_substantive_footer": footer_wc >= 100,
        "schema_types":           schema_types,
        "has_product_schema":     has_product,
        "has_breadcrumb_schema":  has_breadcrumb,
        "has_faq_schema":         has_faq,
        "img_count":              len(imgs),
        "img_no_alt":             img_no_alt,
        "internal_link_count":    internal,
        "external_link_count":    external,
        "issues":                 issues,
    }


if __name__ == "__main__":
    import sys, json
    target = sys.argv[1] if len(sys.argv) > 1 else "https://vinodcookware.com/collections/kadai-2"
    print(json.dumps(audit(target), indent=2, ensure_ascii=False))
