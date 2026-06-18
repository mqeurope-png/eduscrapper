from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import USER_AGENT, get_settings
from .logger import get_logger
from .models import Company

logger = get_logger()

CANDIDATE_PATHS = [
    "/",
    # English
    "/contact", "/contact-us", "/about", "/about-us",
    "/imprint", "/legal", "/legal-notice", "/privacy-policy",
    # Spanish
    "/contacto", "/contactenos", "/empresa", "/quienes-somos",
    "/aviso-legal", "/politica-de-privacidad", "/privacidad",
    # German
    "/kontakt", "/impressum", "/datenschutz", "/ueber-uns", "/uber-uns",
    # Italian
    "/contatti", "/chi-siamo", "/contattaci",
    # French
    "/nous-contacter", "/contactez-nous", "/a-propos", "/mentions-legales",
    # Portuguese
    "/contato", "/contactos", "/sobre",
    # Dutch
    "/contact-opnemen", "/over-ons",
    # Polish / Czech / Slovak
    "/o-nas", "/o-firmie", "/kontakty",
    # Hungarian
    "/kapcsolat",
    # Romanian
    "/despre-noi",
    # Turkish
    "/iletisim", "/hakkimizda",
]

_PAGE_TYPE = {
    # contact-style
    "contact": "contact", "contacto": "contact", "contactenos": "contact",
    "contatti": "contact", "contattaci": "contact",
    "kontakt": "contact", "kontakty": "contact",
    "kapcsolat": "contact", "iletisim": "contact",
    "contato": "contact", "contactos": "contact", "contact-opnemen": "contact",
    "nous-contacter": "contact", "contactez-nous": "contact",
    # legal / imprint / privacy
    "aviso-legal": "legal", "legal": "legal", "legal-notice": "legal",
    "imprint": "legal", "impressum": "legal", "mentions-legales": "legal",
    "datenschutz": "privacy", "privacidad": "privacy",
    "politica-de-privacidad": "privacy", "privacy-policy": "privacy",
    # about-style
    "empresa": "about", "quienes-somos": "about", "about": "about",
    "about-us": "about", "chi-siamo": "about", "ueber-uns": "about",
    "uber-uns": "about", "a-propos": "about", "sobre": "about",
    "over-ons": "about", "o-nas": "about", "o-firmie": "about",
    "despre-noi": "about", "hakkimizda": "about",
}

_BLOCKED = ("login", "signin", "wp-login", "/cart", "captcha")

# Anchor text/href fragments that suggest a contact/legal/about page in *any*
# language. Used by `_discover_paths` to follow the site's own links rather
# than brute-forcing URL paths.
_DISCOVER_HINTS = (
    # English
    "contact", "about", "imprint", "legal",
    # Spanish
    "contacto", "contactenos", "empresa", "quienes", "aviso",
    # German
    "kontakt", "impressum", "datenschutz", "uber", "ueber",
    # Italian
    "contatti", "contattaci", "chi siamo", "chi-siamo",
    # French
    "nous contacter", "contactez", "mentions", "a propos", "à propos",
    # Portuguese
    "contato", "contactos", "sobre",
    # Dutch
    "over ons", "over-ons",
    # Polish/Czech/Slovak
    "o nas", "o-nas", "o firmie", "kontakty",
    # Hungarian
    "kapcsolat",
    # Turkish
    "iletisim", "iletişim", "hakkimizda", "hakkımızda",
    # Romanian
    "despre",
)


@dataclass
class PageResult:
    company_name: str
    domain: str
    url: str
    status_code: int = 0
    title: str = ""
    text: str = ""
    html: str = ""
    page_type: str = "home"
    error: str = ""


@dataclass
class ScrapeResult:
    company: Company
    pages: List[PageResult] = field(default_factory=list)


def _page_type(path: str) -> str:
    for key, value in _PAGE_TYPE.items():
        if key in path:
            return value
    return "home"


def _base_url(company: Company) -> str:
    if company.website:
        return company.website.rstrip("/")
    if company.domain:
        return f"https://{company.domain}"
    return ""


def _fetch(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        return client.get(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.warning("Request failed %s: %s", url, exc)
        return None


def _discover_paths(html: str, base: str) -> list[str]:
    """Return URLs from anchors whose text/href hints at contact/about/legal.

    Looks at the actual links in the page rather than guessing. Returns
    absolute URLs (or path-only if same-host). Already filtered to the same
    registered domain to avoid hopping off-site.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(base).netloc.lower()
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        text = (a.get_text(" ", strip=True) or "").lower()
        href_lc = href.lower()
        if not any(h in href_lc or h in text for h in _DISCOVER_HINTS):
            continue
        url = urljoin(base + "/", href)
        host = urlparse(url).netloc.lower()
        # Stay on the same registered domain (allow www. and bare).
        if host and base_host and not (
            host == base_host
            or host.endswith("." + base_host)
            or base_host.endswith("." + host)
        ):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _page_type_for_url(url: str) -> str:
    return _page_type(urlparse(url).path)


def scrape_company(company: Company, max_pages: int, timeout: int) -> ScrapeResult:
    result = ScrapeResult(company=company)
    base = _base_url(company)
    if not base:
        return result

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}
    seen: set[str] = set()

    def visit(client: httpx.Client, url: str, page_type: str) -> None:
        if len(result.pages) >= max_pages:
            return
        if url in seen or any(b in url.lower() for b in _BLOCKED):
            return
        seen.add(url)
        resp = _fetch(client, url)
        if resp is None:
            result.pages.append(
                PageResult(
                    company_name=company.company_name,
                    domain=company.domain,
                    url=url,
                    page_type=page_type,
                    error="request_failed",
                )
            )
            return
        page = PageResult(
            company_name=company.company_name,
            domain=company.domain,
            url=str(resp.url),
            status_code=resp.status_code,
            page_type=page_type,
        )
        if resp.status_code == 200 and "text/html" in resp.headers.get(
            "content-type", ""
        ):
            soup = BeautifulSoup(resp.text, "lxml")
            page.title = soup.title.get_text(strip=True) if soup.title else ""
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            page.text = soup.get_text(" ", strip=True)
            page.html = resp.text
        result.pages.append(page)
        time.sleep(0.3)

    with httpx.Client(
        headers=headers, timeout=timeout, verify=False, http2=False
    ) as client:
        # 1) Home first — we need its HTML to discover real links.
        visit(client, base, "home")

        # 2) Follow real anchor links from the home that look like
        #    contact/about/legal in any language. This adapts to whatever URL
        #    scheme the site actually uses (e.g. /Kontakt.html, /en/contact).
        home_html = result.pages[0].html if result.pages else ""
        for url in _discover_paths(home_html, base):
            if len(result.pages) >= max_pages:
                break
            visit(client, url, _page_type_for_url(url))

        # 3) Fallback: brute-force common multilingual paths for anything we
        #    haven't covered yet (sites without nav links to contact).
        for path in CANDIDATE_PATHS:
            if len(result.pages) >= max_pages:
                break
            url = base + path if path != "/" else base
            visit(client, url, _page_type(path))
    return result


def scrape_companies(
    companies: List[Company], progress_cb=None, checkpoint_cb=None,
    checkpoint_every: int = 200,
) -> List[ScrapeResult]:
    settings = get_settings()
    results: List[ScrapeResult] = []
    total = len(companies)
    with ThreadPoolExecutor(max_workers=settings.max_concurrent_requests) as pool:
        futures = [
            pool.submit(
                scrape_company,
                c,
                settings.max_pages_per_domain,
                settings.request_timeout,
            )
            for c in companies
        ]
        for idx, future in enumerate(futures, start=1):
            results.append(future.result())
            if progress_cb:
                progress_cb(idx, total)
            if checkpoint_cb and (idx % checkpoint_every == 0 or idx == total):
                try:
                    checkpoint_cb(results)
                except Exception:
                    pass
    return results
