from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import tldextract

from .config import get_settings
from .logger import get_logger

logger = get_logger()
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

# Never return these as a "corporate website".
BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "pinterest.com", "wikipedia.org",
    "wikidata.org", "google.com", "google.es", "maps.google.com",
    "sites.google.com", "business.site", "paginasamarillas.es", "yelp.com",
    "tripadvisor.com", "mercadolibre.com", "amazon.com", "amazon.es",
    "ebay.com", "glassdoor.com", "indeed.com", "europages.es", "axesor.es",
    "einforma.com", "infoempresa.com", "expansion.com", "wordpress.com",
    "blogspot.com", "wixsite.com", "weebly.com", "jimdo.com", "jimdofree.com",
    "crunchbase.com", "empresite.eleconomista.es",
}

PROMPT_TEMPLATE = (
    "Encuentra el sitio web corporativo OFICIAL de la siguiente empresa "
    "usando búsqueda web. No inventes dominios.\n\n"
    "Empresa: {company}\n"
    "Localización: {location}\n"
    "Pista de sector: {hint}\n\n"
    "Reglas:\n"
    "- Devuelve el dominio registrado (por ejemplo \"empresa.es\"), no una "
    "subpágina ni una subdomain de marketplace.\n"
    "- NO devuelvas redes sociales, directorios de empresas, marketplaces, "
    "Google Maps, Wikipedia ni perfiles en plataformas de terceros.\n"
    "- Si no estás seguro, devuelve domain vacío y confidence \"none\".\n"
    "- No expliques: responde SOLO con JSON válido.\n\n"
    "Formato exacto:\n"
    "{{\"domain\": \"\", \"url\": \"\", \"confidence\": \"high|medium|low|none\","
    " \"reason\": \"explicación breve\"}}"
)


@dataclass
class Resolution:
    company_name: str
    query: str
    chosen_domain: str = ""
    chosen_url: str = ""
    confidence: str = "none"
    reason: str = ""
    provider: str = "openai_web_search"
    error: str = ""


def _registered_domain(value: str) -> str:
    if not value:
        return ""
    candidate = value if "://" in value else "https://" + value
    ext = _EXTRACT(candidate)
    if not ext.domain:
        return ""
    parts = [ext.domain]
    if ext.suffix:
        parts.append(ext.suffix)
    return ".".join(parts).lower()


def _slug(value: str) -> str:
    norm = unicodedata.normalize("NFKD", value or "")
    norm = norm.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", norm.lower())


def _confidence_from_match(company: str, domain: str, model_confidence: str) -> str:
    """Combine the model's self-confidence with a slug overlap heuristic."""
    if not domain:
        return "none"
    company_slug = _slug(company)
    domain_slug = _slug(domain.split(".")[0])
    if company_slug and domain_slug:
        if company_slug == domain_slug:
            return "high"
        if company_slug in domain_slug or domain_slug in company_slug:
            return "high" if model_confidence == "high" else "medium"
    if model_confidence in {"high", "medium", "low", "none"}:
        return model_confidence
    return "low"


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _openai_search(prompt: str, model: str) -> str:
    """Call the OpenAI Responses API with the web_search tool. Returns text."""
    from openai import OpenAI

    client = OpenAI(api_key=get_settings().openai_api_key)
    resp = client.responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        input=prompt,
    )
    text = getattr(resp, "output_text", "") or ""
    if text:
        return text
    # Fallback: walk the output blocks for any text content.
    chunks: List[str] = []
    for item in getattr(resp, "output", []) or []:
        for c in getattr(item, "content", []) or []:
            t = getattr(c, "text", None)
            if t:
                chunks.append(t)
    return "\n".join(chunks)


def resolve_domain(
    company_name: str,
    location: str = "",
    hint: str = "",
    search_fn: Optional[Callable[[str, str], str]] = None,
) -> Resolution:
    """Resolve a corporate domain for a company using web search.

    `search_fn(prompt, model) -> raw_text` can be injected for tests.
    """
    company = (company_name or "").strip()
    if not company:
        return Resolution(company_name="", query="", error="empty_company")

    settings = get_settings()
    query = f"{company} {location} {hint}".strip()
    prompt = PROMPT_TEMPLATE.format(
        company=company, location=location or "(sin dato)", hint=hint or "(sin dato)"
    )
    fn = search_fn or (lambda p, m: _openai_search(p, m))
    model = settings.openai_search_model or settings.openai_model_fast

    try:
        text = fn(prompt, model)
    except Exception as exc:  # noqa: BLE001 - SDK raises many types
        logger.warning("Domain resolver failed for %s: %s", company, exc)
        return Resolution(company_name=company, query=query, error=str(exc))

    parsed = _parse_json(text) or {}
    raw_domain = str(parsed.get("domain", "") or "")
    raw_url = str(parsed.get("url", "") or "")
    model_conf = str(parsed.get("confidence", "none") or "none").lower()
    reason = str(parsed.get("reason", "") or "")

    domain = _registered_domain(raw_domain or raw_url)
    if not domain or domain in BLOCKED_DOMAINS:
        return Resolution(
            company_name=company,
            query=query,
            chosen_url=raw_url,
            confidence="none",
            reason=reason or "blocked_or_empty_domain",
        )

    confidence = _confidence_from_match(company, domain, model_conf)
    return Resolution(
        company_name=company,
        query=query,
        chosen_domain=domain,
        chosen_url=raw_url or f"https://{domain}",
        confidence=confidence,
        reason=reason,
    )


def resolve_missing_domains(
    companies, progress_cb=None, search_fn: Optional[Callable] = None
) -> List[Resolution]:
    """Mutate companies in place: for every company without a domain, run the
    resolver and fill in the domain/website when confident enough.
    """
    from .normalize import normalize_domain, normalize_website

    resolutions: List[Resolution] = []
    total = len(companies)
    for idx, c in enumerate(companies, start=1):
        if c.domain:
            if progress_cb:
                progress_cb(idx, total)
            continue
        location = c.state_or_province or c.country
        res = resolve_domain(c.company_name, location, c.industry_hint, search_fn=search_fn)
        resolutions.append(res)
        if res.chosen_domain and res.confidence in {"high", "medium"}:
            c.domain = normalize_domain(res.chosen_domain)
            if not c.website:
                c.website = normalize_website("", c.domain)
            tag = "resolved_via=openai_web_search"
            c.source = (c.source + " | " + tag).strip(" |")
        if progress_cb:
            progress_cb(idx, total)
    return resolutions
