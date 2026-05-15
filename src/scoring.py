from __future__ import annotations

from urllib.parse import urlparse

import tldextract

from .models import EmailMatch

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
    "yahoo.es",
    "hotmail.es",
    "live.com",
    "icloud.com",
}

GENERIC_LOCAL_PARTS = {
    "info",
    "contacto",
    "contact",
    "comercial",
    "ventas",
    "administracion",
    "hola",
    "hello",
    "sales",
}

PROVIDER_HINTS = (
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


def _registered_domain(value: str) -> str:
    if "://" not in value and "@" not in value:
        value = "https://" + value
    if "@" in value:
        value = value.split("@")[-1]
    host = urlparse(value if "://" in value else "https://" + value).netloc or value
    ext = _EXTRACT(host)
    if not ext.domain:
        return host.lower()
    parts = [ext.domain]
    if ext.suffix:
        parts.append(ext.suffix)
    return ".".join(parts).lower()


def score_match(match: EmailMatch) -> tuple[float, str]:
    """Deterministic pre-AI score and a flag. Higher = more trustworthy."""
    score = 0.0
    flags: list[str] = []

    target = match.target_domain.lower()
    email_domain = match.email_domain.lower()
    source_domain = _registered_domain(match.source_url) if match.source_url else ""
    local_part = match.email.split("@")[0].lower()
    context_lc = (match.text_context or "").lower()

    domain_matches = bool(target) and email_domain == target
    source_is_target = bool(target) and source_domain == target

    if domain_matches and source_is_target:
        score += 5.0
        flags.append("domain_and_source_match")
    elif domain_matches:
        score += 3.0
        flags.append("email_domain_match")
    elif source_is_target:
        score += 1.0
        flags.append("source_match_only")
    else:
        score -= 2.0
        flags.append("domain_mismatch")

    if match.page_type in {"contact", "legal", "privacy"}:
        score += 2.0
        flags.append(f"page_{match.page_type}")

    if local_part in GENERIC_LOCAL_PARTS:
        score += 1.5
        flags.append("generic_corporate")

    if email_domain in FREE_EMAIL_DOMAINS:
        score -= 2.0
        flags.append("free_email")

    if any(hint in context_lc for hint in PROVIDER_HINTS) and not domain_matches:
        score -= 4.0
        flags.append("provider_context")

    if not match.source_url:
        score -= 3.0
        flags.append("no_source_url")

    if match.match_type == "generated_candidate":
        score = -1.0
        flags = ["generated_candidate"]

    return round(score, 2), ",".join(flags)


def deterministic_decision(score: float, flag: str) -> tuple[str, bool]:
    """Returns (decision, brevo_recommended) used when AI is unavailable."""
    if "generated_candidate" in flag:
        return "review", False
    if "provider_context" in flag or "domain_mismatch" in flag:
        return ("review", False) if score >= 1.0 else ("reject", False)
    if score >= 5.0:
        return "accept", True
    if score >= 2.0:
        return "review", False
    return "reject", False
