"""Fetch a website safely and reduce it to compact, LLM-ready text."""
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.utils.validators import InvalidURLError, assert_public_host, normalize_url

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LinkAnalysisBot/1.0)", "Accept": "text/html,*/*;q=0.8"}
EXTRA_PAGE_RE = re.compile(r"/(about|services?|solutions?|products?|what-we-do|pricing)(/|$|\.)", re.I)
NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe", "nav", "footer", "aside", "form"]


class FetchError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class PageContent:
    url: str
    title: str = ""
    description: str = ""
    site_name: str = ""
    headings: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    structured: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


async def fetch_html(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    """GET with manual redirects so every hop is SSRF-checked; capped body size."""
    s = get_settings()
    current = url
    for _ in range(5):
        await assert_public_host(current)
        try:
            async with client.stream("GET", current, headers=HEADERS, follow_redirects=False) as r:
                if r.is_redirect:
                    loc = r.headers.get("location")
                    if not loc:
                        raise FetchError("site_unreachable", "Redirect without location.")
                    current = normalize_url(urljoin(current, loc))
                    continue
                if r.status_code in (401, 403, 429):
                    raise FetchError("site_blocked", f"Website refused access (HTTP {r.status_code}).")
                if r.status_code >= 400:
                    raise FetchError("site_unreachable", f"Website returned HTTP {r.status_code}.")
                if "html" not in r.headers.get("content-type", "").lower():
                    raise FetchError("no_content", "URL did not return an HTML page.")
                buf, size = [], 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    buf.append(chunk)
                    if size > s.max_page_bytes:
                        break
                return current, b"".join(buf).decode(r.encoding or "utf-8", errors="replace")
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise FetchError("site_unreachable", f"Could not reach website: {type(e).__name__}.")
    raise FetchError("site_unreachable", "Too many redirects.")


def parse_page(html: str, url: str) -> PageContent:
    soup = BeautifulSoup(html, "html.parser")
    page = PageContent(url=url)
    page.title = soup.title.get_text(strip=True) if soup.title else ""

    def meta(**attrs):
        tag = soup.find("meta", attrs=attrs)
        return (tag.get("content") or "").strip() if tag else ""

    page.description = meta(name="description") or meta(property="og:description")
    page.site_name = meta(property="og:site_name")

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            for item in (data if isinstance(data, list) else [data]):
                if isinstance(item, dict) and item.get("name"):
                    page.structured.append(f"{item.get('@type', '')}: {item['name']} - {str(item.get('description', ''))[:200]}")
        except (ValueError, TypeError):
            pass

    host = urlsplit(url).netloc
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if urlsplit(href).netloc == host and EXTRA_PAGE_RE.search(urlsplit(href).path) and href not in page.links:
            page.links.append(href.split("#")[0])

    for t in soup(NOISE_TAGS):
        t.decompose()
    seen = set()
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        is_h = el.name.startswith("h")
        if len(text) < (3 if is_h else 30) or text.lower() in seen:
            continue
        seen.add(text.lower())
        (page.headings if is_h else page.lines).append(text[:300])
    return page


def to_prompt_text(pages: list[PageContent], max_chars: int) -> str:
    out = []
    for p in pages:
        block = [f"## PAGE: {p.url}", f"Title: {p.title}", f"Meta description: {p.description}"]
        if p.site_name:
            block.append(f"Site name: {p.site_name}")
        block += [f"Structured data: {s}" for s in p.structured[:3]]
        if p.headings:
            block.append("Headings: " + " | ".join(p.headings[:40]))
        block.append("Text:\n" + "\n".join(p.lines))
        out.append("\n".join(block))
    return "\n\n".join(out)[:max_chars]


async def extract_website(url: str) -> tuple[str, str, list[str]]:
    """Returns (final_url, cleaned_text_for_llm, pages_analyzed)."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=s.fetch_timeout_s) as client:
        final_url, html = await fetch_html(client, url)
        home = parse_page(html, final_url)
        pages = [home]
        for link in home.links[:2]:  # up to 2 extra pages (about/services) for better grounding
            try:
                u, h = await fetch_html(client, normalize_url(link))
                pages.append(parse_page(h, u))
            except (FetchError, InvalidURLError, ValueError):
                continue
    text = to_prompt_text(pages, s.max_content_chars)
    if len(text) < 200 or not (home.headings or home.lines):
        raise FetchError("no_content", "Not enough readable content found (page may be JavaScript-rendered).")
    return final_url, text, [p.url for p in pages]
