from __future__ import annotations

import re
from typing import List

import tldextract

from .models import EmailMatch
from .scraper import ScrapeResult

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

EMAIL_RE = re.compile(
    r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE
)

# info [at] dominio.com / info(at)dominio.com / info[@]dominio.com
OBFUSCATED_AT_RE = re.compile(
    r"([A-Z0-9._%+\-]+)\s*[\(\[\{]?\s*(?:@|at|arroba)\s*[\)\]\}]?\s*"
    r"([A-Z0-9.\-]+\.[A-Z]{2,})",
    re.IGNORECASE,
)

# info arroba dominio punto com
OBFUSCATED_WORDS_RE = re.compile(
    r"([A-Z0-9._%+\-]+)\s+(?:arroba|at)\s+([A-Z0-9.\-]+)\s+(?:punto|dot)\s+([A-Z]{2,})",
    re.IGNORECASE,
)

_EXAMPLE_DOMAINS = {
    "example.com",
    "example.org",
    "domain.com",
    "dominio.com",
    "email.com",
    "tudominio.com",
    "yourdomain.com",
    "sentry.io",
    "wixpress.com",
}

_PROVIDER_HINTS = (
    "diseño web",
    "diseno web",
    "desarrollado por",
    "powered by",
    "hosting",
    "seo",
    "marketing agency",
    "agencia de marketing",
    "web design",
    "developed by",
)


def _registered_domain(host: str) -> str:
    ext = _EXTRACT(host)
    if not ext.domain:
        return host.lower()
    parts = [ext.domain]
    if ext.suffix:
        parts.append(ext.suffix)
    return ".".join(parts).lower()


def _clean_email(raw: str) -> str:
    email = raw.strip().strip(".,;:)('\"<>").lower()
    email = email.replace("mailto:", "")
    return email


def _context(text: str, token: str, width: int = 160) -> str:
    idx = text.lower().find(token.lower())
    if idx == -1:
        return ""
    start = max(0, idx - width)
    end = min(len(text), idx + len(token) + width)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _is_junk(email: str, context_lc: str) -> bool:
    domain = email.split("@")[-1]
    if _registered_domain(domain) in _EXAMPLE_DOMAINS:
        return True
    if email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return True
    if any(hint in context_lc for hint in _PROVIDER_HINTS):
        # Keep but flagged elsewhere only if it matches target; here drop clear provider noise
        if "@" in email and _registered_domain(domain) not in context_lc:
            return False
    return False


def extract_from_scrape(scrape: ScrapeResult) -> List[EmailMatch]:
    matches: List[EmailMatch] = []
    seen: set[str] = set()
    target_domain = scrape.company.domain

    for page in scrape.pages:
        if not page.text and not page.html:
            continue
        haystacks: list[tuple[str, str]] = []
        if page.html:
            for m in re.finditer(
                r"mailto:([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})",
                page.html,
                re.IGNORECASE,
            ):
                haystacks.append((_clean_email(m.group(1)), "mailto"))
        text = page.text or ""
        for m in EMAIL_RE.finditer(text):
            haystacks.append((_clean_email(m.group(0)), "exact_public_email"))
        for m in OBFUSCATED_AT_RE.finditer(text):
            haystacks.append(
                (_clean_email(f"{m.group(1)}@{m.group(2)}"), "obfuscated_public_email")
            )
        for m in OBFUSCATED_WORDS_RE.finditer(text):
            haystacks.append(
                (
                    _clean_email(f"{m.group(1)}@{m.group(2)}.{m.group(3)}"),
                    "obfuscated_public_email",
                )
            )

        context_lc = text.lower()
        for email, match_type in haystacks:
            if not email or "@" not in email:
                continue
            if "." not in email.split("@")[-1]:
                continue
            if _is_junk(email, context_lc):
                continue
            dedup = f"{page.url}|{email}"
            if dedup in seen:
                continue
            seen.add(dedup)
            matches.append(
                EmailMatch(
                    company_name=scrape.company.company_name,
                    target_domain=target_domain,
                    email=email,
                    email_domain=_registered_domain(email.split("@")[-1]),
                    source_url=page.url,
                    page_type=page.page_type,
                    text_context=_context(text, email) or page.title,
                    match_type=match_type,  # type: ignore[arg-type]
                )
            )
    return matches
