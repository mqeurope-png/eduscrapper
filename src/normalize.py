from __future__ import annotations

import re
from urllib.parse import urlparse

import tldextract

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_email(email: str | None) -> str:
    if not email:
        return ""
    value = str(email).strip().lower().replace("mailto:", "")
    value = value.strip(" .,;:()[]{}<>\"'")
    return value


def normalize_company(name: str | None) -> str:
    return clean_text(name)


def normalize_website(website: str | None, domain: str | None = "") -> str:
    website = clean_text(website)
    domain = clean_text(domain)
    if not website and domain:
        return f"https://{domain.lstrip('/').lower()}"
    if not website:
        return ""
    if not re.match(r"^https?://", website, re.IGNORECASE):
        website = "https://" + website
    parsed = urlparse(website)
    netloc = parsed.netloc.lower()
    scheme = parsed.scheme.lower() or "https"
    return f"{scheme}://{netloc}{parsed.path}".rstrip("/") or f"{scheme}://{netloc}"


def normalize_domain(domain: str | None, website: str | None = "") -> str:
    candidate = clean_text(domain)
    if not candidate and website:
        candidate = clean_text(website)
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = "https://" + candidate
    ext = _EXTRACT(candidate)
    if not ext.domain:
        return ""
    parts = [ext.domain]
    if ext.suffix:
        parts.append(ext.suffix)
    return ".".join(parts).lower()


def normalize_phone(phone: str | None, default_cc: str = "+34") -> str:
    phone = clean_text(phone)
    if not phone:
        return ""
    has_plus = phone.strip().startswith("+")
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return ""
    if has_plus:
        return "+" + digits
    if len(digits) == 9:
        return f"{default_cc}{digits}"
    if digits.startswith("34") and len(digits) == 11:
        return "+" + digits
    return digits


_PROVINCE_FIX = {
    "a coruna": "A Coruña",
    "la coruna": "A Coruña",
    "alava": "Álava",
    "almeria": "Almería",
    "avila": "Ávila",
    "caceres": "Cáceres",
    "cadiz": "Cádiz",
    "cordoba": "Córdoba",
    "gipuzkoa": "Gipuzkoa",
    "guipuzcoa": "Gipuzkoa",
    "jaen": "Jaén",
    "leon": "León",
    "malaga": "Málaga",
    "vizcaya": "Bizkaia",
    "bizkaia": "Bizkaia",
}


def normalize_province(province: str | None) -> str:
    province = clean_text(province)
    if not province:
        return ""
    key = province.lower()
    if key in _PROVINCE_FIX:
        return _PROVINCE_FIX[key]
    return province.title()


def dedupe_key(company_name: str, domain: str) -> str:
    return f"{normalize_company(company_name).lower()}|{normalize_domain(domain).lower()}"
