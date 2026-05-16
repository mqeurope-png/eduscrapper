from __future__ import annotations

from typing import List

import tldextract

from .models import Company, EmailMatch

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

# Prefixes allowed per mode. Order matters (kept stable for output).
CANDIDATE_MODES: dict[str, list[str]] = {
    "none": [],
    "conservative": ["info", "contacto"],
    "standard": ["info", "contacto", "comercial"],
    "broad": ["info", "contacto", "comercial", "ventas", "hola", "administracion"],
}

# Prefixes that may ever be recommended to Brevo once verified.
ALLOWED_CANDIDATE_PREFIXES = {
    "info",
    "contacto",
    "comercial",
    "ventas",
    "hola",
    "administracion",
}

# Free / non-corporate / social / directory / hosting domains: never generate
# generic candidates against these (a candidate there would be meaningless).
NON_CORPORATE_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "hotmail.es",
    "outlook.com",
    "outlook.es",
    "live.com",
    "yahoo.com",
    "yahoo.es",
    "icloud.com",
    "aol.com",
    "protonmail.com",
    "gmx.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "google.com",
    "google.es",
    "maps.google.com",
    "business.site",
    "sites.google.com",
    "wix.com",
    "wixsite.com",
    "wordpress.com",
    "blogspot.com",
    "weebly.com",
    "godaddy.com",
    "wordpress.org",
    "amazon.com",
    "amazon.es",
    "mercadolibre.com",
    "ebay.com",
    "paginasamarillas.es",
    "yelp.com",
    "tripadvisor.com",
}


def _registered_domain(domain: str) -> str:
    ext = _EXTRACT(domain if "://" in domain else "https://" + domain)
    if not ext.domain:
        return domain.lower()
    parts = [ext.domain]
    if ext.suffix:
        parts.append(ext.suffix)
    return ".".join(parts).lower()


def is_corporate_domain(domain: str) -> bool:
    if not domain:
        return False
    return _registered_domain(domain) not in NON_CORPORATE_DOMAINS


def generate_candidates(company: Company, mode: str = "conservative") -> List[EmailMatch]:
    """Generate generic candidates for a company according to the mode.

    Only for companies with a valid corporate domain. Returns [] for the
    "none" mode, unknown modes, or non-corporate domains.
    """
    prefixes = CANDIDATE_MODES.get(mode, [])
    if not prefixes or not company.domain or not is_corporate_domain(company.domain):
        return []

    domain = company.domain.lower()
    candidates: List[EmailMatch] = []
    seen: set[str] = set()
    for prefix in prefixes:
        email = f"{prefix}@{domain}"
        if email in seen:
            continue
        seen.add(email)
        candidates.append(
            EmailMatch(
                company_name=company.company_name,
                target_domain=company.domain,
                email=email,
                email_domain=domain,
                source_url="",
                page_type="generated",
                text_context="candidate_only not_publicly_found must_verify",
                match_type="generated_candidate",
                candidate_mode=mode,
                source_basis="generated_generic_pattern",
                must_verify=True,
            )
        )
    return candidates
