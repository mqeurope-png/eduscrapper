from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List

import httpx
from bs4 import BeautifulSoup

from .config import USER_AGENT, get_settings
from .logger import get_logger
from .models import Company

logger = get_logger()

CANDIDATE_PATHS = [
    "/",
    "/contacto",
    "/contact",
    "/contacto/",
    "/aviso-legal",
    "/legal",
    "/politica-de-privacidad",
    "/privacidad",
    "/privacy-policy",
    "/empresa",
    "/quienes-somos",
    "/about",
]

_PAGE_TYPE = {
    "contacto": "contact",
    "contact": "contact",
    "aviso-legal": "legal",
    "legal": "legal",
    "politica-de-privacidad": "privacy",
    "privacidad": "privacy",
    "privacy-policy": "privacy",
    "empresa": "about",
    "quienes-somos": "about",
    "about": "about",
}

_BLOCKED = ("login", "signin", "wp-login", "/cart", "captcha")


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


def scrape_company(company: Company, max_pages: int, timeout: int) -> ScrapeResult:
    result = ScrapeResult(company=company)
    base = _base_url(company)
    if not base:
        return result

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}
    seen: set[str] = set()
    with httpx.Client(
        headers=headers, timeout=timeout, verify=False, http2=False
    ) as client:
        for path in CANDIDATE_PATHS:
            if len(result.pages) >= max_pages:
                break
            url = base + path if path != "/" else base
            if url in seen or any(b in url.lower() for b in _BLOCKED):
                continue
            seen.add(url)
            resp = _fetch(client, url)
            if resp is None:
                result.pages.append(
                    PageResult(
                        company_name=company.company_name,
                        domain=company.domain,
                        url=url,
                        page_type=_page_type(path),
                        error="request_failed",
                    )
                )
                continue
            page = PageResult(
                company_name=company.company_name,
                domain=company.domain,
                url=str(resp.url),
                status_code=resp.status_code,
                page_type=_page_type(path),
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
    return result


def scrape_companies(companies: List[Company], progress_cb=None) -> List[ScrapeResult]:
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
    return results
