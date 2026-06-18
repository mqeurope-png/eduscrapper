from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, List, Optional

import httpx
import tldextract

from .config import get_settings
from .logger import get_logger

logger = get_logger()
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "pinterest.com", "wikipedia.org",
    "wikidata.org", "google.com", "google.es", "maps.google.com",
    "sites.google.com", "business.site", "paginasamarillas.es", "yelp.com",
    "tripadvisor.com", "mercadolibre.com", "amazon.com", "amazon.es",
    "ebay.com", "glassdoor.com", "indeed.com", "europages.es", "axesor.es",
    "einforma.com", "infoempresa.com", "expansion.com", "wordpress.com",
    "blogspot.com", "wixsite.com", "weebly.com", "jimdo.com", "jimdofree.com",
    "crunchbase.com", "empresite.eleconomista.es", "bing.com", "duckduckgo.com",
}

# ---- shared helpers --------------------------------------------------------

@dataclass
class Resolution:
    company_name: str
    query: str
    chosen_domain: str = ""
    chosen_url: str = ""
    confidence: str = "none"
    reason: str = ""
    provider: str = ""
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


# ---- provider 1: OpenAI Responses + web_search -----------------------------

OPENAI_PROMPT = (
    "Encuentra el sitio web corporativo OFICIAL de la siguiente empresa "
    "usando búsqueda web. No inventes dominios.\n\n"
    "Empresa: {company}\n"
    "Localización: {location}\n"
    "Pista de sector: {hint}\n\n"
    "Reglas:\n"
    "- Devuelve el dominio registrado (\"empresa.es\"), no subpágina ni "
    "subdomain de marketplace.\n"
    "- NO redes sociales, directorios, marketplaces, Maps, Wikipedia ni "
    "perfiles en plataformas de terceros.\n"
    "- Si no estás seguro, domain vacío y confidence \"none\".\n"
    "- Responde SOLO con JSON:\n"
    "{{\"domain\": \"\", \"url\": \"\", \"confidence\": "
    "\"high|medium|low|none\", \"reason\": \"explicación breve\"}}"
)


def _openai_search_call(prompt: str, model: str) -> str:
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
    chunks: List[str] = []
    for item in getattr(resp, "output", []) or []:
        for c in getattr(item, "content", []) or []:
            t = getattr(c, "text", None)
            if t:
                chunks.append(t)
    return "\n".join(chunks)


def _resolve_openai(
    company: str,
    location: str,
    hint: str,
    search_fn: Optional[Callable[[str, str], str]],
) -> Resolution:
    settings = get_settings()
    query = f"{company} {location} {hint}".strip()
    prompt = OPENAI_PROMPT.format(
        company=company, location=location or "(sin dato)", hint=hint or "(sin dato)"
    )
    fn = search_fn or _openai_search_call
    model = settings.openai_search_model or settings.openai_model_fast

    try:
        text = fn(prompt, model)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Domain resolver (OpenAI) failed for %s: %s", company, exc)
        return Resolution(
            company_name=company, query=query, provider="openai_web_search",
            error=str(exc),
        )

    parsed = _parse_json(text) or {}
    raw_domain = str(parsed.get("domain", "") or "")
    raw_url = str(parsed.get("url", "") or "")
    model_conf = str(parsed.get("confidence", "none") or "none").lower()
    reason = str(parsed.get("reason", "") or "")

    domain = _registered_domain(raw_domain or raw_url)
    if not domain or domain in BLOCKED_DOMAINS:
        return Resolution(
            company_name=company, query=query,
            provider="openai_web_search",
            chosen_url=raw_url, confidence="none",
            reason=reason or "blocked_or_empty_domain",
        )
    return Resolution(
        company_name=company, query=query,
        provider="openai_web_search",
        chosen_domain=domain, chosen_url=raw_url or f"https://{domain}",
        confidence=_confidence_from_match(company, domain, model_conf),
        reason=reason,
    )


# ---- provider 2: Brave Search + gpt-4o-mini classifier ---------------------

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


# Brave's web search "country" parameter only accepts these market codes;
# anything else returns HTTP 422 and the whole resolution falls to "none".
# Source: https://api.search.brave.com/app/documentation/web-search/codes
_BRAVE_SUPPORTED_COUNTRIES = {
    "AR", "AU", "AT", "BE", "BR", "CA", "CL", "DK", "FI", "FR", "DE",
    "HK", "IN", "ID", "IT", "JP", "KR", "MY", "MX", "NL", "NZ", "NO",
    "CN", "PL", "PT", "PH", "RU", "SA", "ZA", "ES", "SE", "CH", "TW",
    "TR", "GB", "US",
}

_COUNTRY_TO_BRAVE = {
    "spain": "ES", "españa": "ES", "espana": "ES",
    "portugal": "PT",
    "france": "FR",
    "germany": "DE", "deutschland": "DE",
    "italy": "IT", "italia": "IT",
    "netherlands": "NL", "holland": "NL",
    "belgium": "BE", "belgique": "BE",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "poland": "PL", "polska": "PL",
    "turkey": "TR", "türkiye": "TR", "turkiye": "TR",
    "switzerland": "CH",
    "austria": "AT", "österreich": "AT", "osterreich": "AT",
    "denmark": "DK",
    "sweden": "SE",
    "norway": "NO",
    "finland": "FI",
    "russia": "RU",
    "united states of america": "US", "usa": "US", "united states": "US",
    "canada": "CA",
    "mexico": "MX", "méxico": "MX",
    "brazil": "BR", "brasil": "BR",
    "argentina": "AR",
    "chile": "CL",
    "australia": "AU",
    "new zealand": "NZ",
    "south africa": "ZA",
    "japan": "JP",
    "south korea": "KR", "korea": "KR",
    "people's republic of china": "CN", "china": "CN",
    "taiwan, china": "TW", "taiwan": "TW",
    "hong kong": "HK",
    "india": "IN",
    "indonesia": "ID",
    "malaysia": "MY",
    "philippines": "PH",
    "saudi arabia": "SA",
}


def _brave_country_for(country: str, fallback: str) -> str:
    """Pick a Brave-supported country code or drop the filter.

    Logic:
      * If the company's country maps to a Brave-supported code -> use it.
      * If the company HAS a country but Brave doesn't support it (UAE, LV,
        RO, GR, RS, MA, CZ...), return empty so we DON'T filter by country;
        forcing the ES default would bias the results to Spain.
      * If the company has NO country at all, use the .env fallback (only
        if Brave supports it). Otherwise empty.
    """
    key = (country or "").strip().lower()
    if key:
        code = _COUNTRY_TO_BRAVE.get(key)
        if code and code in _BRAVE_SUPPORTED_COUNTRIES:
            return code
        return ""
    if fallback and fallback.upper() in _BRAVE_SUPPORTED_COUNTRIES:
        return fallback.upper()
    return ""


def _brave_search_call(query: str, country_code: str = "") -> List[dict]:
    settings = get_settings()
    if not settings.brave_api_key:
        raise RuntimeError("BRAVE_API_KEY no está configurada")
    params = {"q": query, "count": 15}
    cc = country_code or settings.brave_country
    if cc:
        params["country"] = cc
    resp = httpx.get(
        BRAVE_ENDPOINT,
        params=params,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": settings.brave_api_key,
        },
        timeout=settings.request_timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("web", {}).get("results", []) or []


BRAVE_CLASSIFY_PROMPT = (
    "Tengo varios resultados de búsqueda para una empresa. Elige cuál es "
    "el sitio web corporativo OFICIAL.\n\n"
    "Empresa: {company}\n"
    "Localización: {location}\n"
    "Sector (contexto, NO criterio): {hint}\n\n"
    "Resultados (filtrados, ya sin redes sociales ni directorios):\n"
    "{results}\n\n"
    "Reglas de decisión:\n"
    "- Si el TÍTULO o la URL contienen el nombre de la empresa o una "
    "variante reconocible (incluyendo acrónimos: p. ej. 'rapidcc.es' "
    "para 'Rapid Centro Color', 'gmgcolor.com' para 'GMG Color'), es "
    "evidencia FUERTE de web oficial → confidence high.\n"
    "- Si solo el snippet/descripción la menciona pero no el título ni "
    "la URL, confidence medium.\n"
    "- Devuelve el dominio registrado (\"empresa.es\"), no subpágina.\n"
    "- NO selecciones marketplaces (alibaba, made-in-china), directorios "
    "(pappers, einforma, kompass, dnb, paginas-amarillas), agregadores "
    "de eventos (eventseye, 10times), agencias generalistas ni "
    "perfiles en plataformas de terceros.\n"
    "- Si ninguno parece la web oficial corporativa, domain vacío y "
    "confidence \"none\".\n"
    "- Responde SOLO con JSON:\n"
    "{{\"index\": <numero o null>, \"domain\": \"\", \"url\": \"\", "
    "\"confidence\": \"high|medium|low|none\", "
    "\"reason\": \"explicación breve\"}}"
)


def _brave_classify_call(prompt: str, model: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=get_settings().openai_api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


def _filter_brave_results(results: List[dict]) -> List[dict]:
    out = []
    seen: set[str] = set()
    for r in results:
        url = r.get("url") or r.get("href") or ""
        dom = _registered_domain(url)
        if not dom or dom in BLOCKED_DOMAINS or dom in seen:
            continue
        seen.add(dom)
        out.append(
            {
                "domain": dom,
                "url": url,
                "title": r.get("title", ""),
                "description": r.get("description", "") or r.get("snippet", ""),
            }
        )
        if len(out) >= 8:
            break
    return out


def _resolve_brave(
    company: str,
    location: str,
    hint: str,
    search_fn: Optional[Callable[[str], List[dict]]],
    classify_fn: Optional[Callable[[str, str], str]],
) -> Resolution:
    settings = get_settings()
    # Brave query: only the company + a short location word. The industry hint
    # is generic ("print, signage, large-format, ...") and pollutes the search
    # so we keep it ONLY as context for the GPT classifier below.
    brave_query = f"{company} {location}".strip() if location else company
    query = f"{company} {location} {hint}".strip()  # for the audit log
    search = search_fn or _brave_search_call
    classify = classify_fn or _brave_classify_call
    country_code = _brave_country_for(location, settings.brave_country)

    try:
        # Older injected search_fn callers may not accept the country kwarg.
        try:
            raw_results = search(brave_query, country_code)  # type: ignore[call-arg]
        except TypeError:
            raw_results = search(brave_query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Brave search failed for %s: %s", company, exc)
        return Resolution(
            company_name=company, query=query, provider="brave",
            error=f"search:{exc}",
        )

    candidates = _filter_brave_results(raw_results)
    if not candidates:
        return Resolution(
            company_name=company, query=query, provider="brave",
            confidence="none", reason="sin_resultados_validos",
        )

    listing = "\n".join(
        f"{i+1}. {c['title']} — {c['url']}\n   {c['description']}"
        for i, c in enumerate(candidates)
    )
    prompt = BRAVE_CLASSIFY_PROMPT.format(
        company=company,
        location=location or "(sin dato)",
        hint=hint or "(sin dato)",
        results=listing,
    )
    model = settings.openai_search_model or settings.openai_model_fast

    try:
        text = classify(prompt, model)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Brave classifier failed for %s: %s", company, exc)
        return Resolution(
            company_name=company, query=query, provider="brave",
            error=f"classify:{exc}",
        )

    parsed = _parse_json(text) or {}
    index = parsed.get("index")
    raw_domain = str(parsed.get("domain", "") or "")
    raw_url = str(parsed.get("url", "") or "")
    model_conf = str(parsed.get("confidence", "none") or "none").lower()
    reason = str(parsed.get("reason", "") or "")

    if not raw_domain and isinstance(index, int) and 1 <= index <= len(candidates):
        raw_domain = candidates[index - 1]["domain"]
        raw_url = raw_url or candidates[index - 1]["url"]

    domain = _registered_domain(raw_domain or raw_url)
    if not domain or domain in BLOCKED_DOMAINS:
        return Resolution(
            company_name=company, query=query, provider="brave",
            chosen_url=raw_url, confidence="none",
            reason=reason or "blocked_or_empty_domain",
        )
    return Resolution(
        company_name=company, query=query, provider="brave",
        chosen_domain=domain, chosen_url=raw_url or f"https://{domain}",
        confidence=_confidence_from_match(company, domain, model_conf),
        reason=reason,
    )


# ---- dispatcher + batch ----------------------------------------------------

def resolve_domain(
    company_name: str,
    location: str = "",
    hint: str = "",
    provider: str = "openai",
    search_fn: Optional[Callable] = None,
    classify_fn: Optional[Callable] = None,
) -> Resolution:
    company = (company_name or "").strip()
    if not company:
        return Resolution(company_name="", query="", provider=provider, error="empty_company")
    if provider == "brave":
        return _resolve_brave(company, location, hint, search_fn, classify_fn)
    return _resolve_openai(company, location, hint, search_fn)


def resolve_missing_domains(
    companies,
    progress_cb=None,
    provider: str = "openai",
    search_fn: Optional[Callable] = None,
    classify_fn: Optional[Callable] = None,
    checkpoint_cb=None,
    checkpoint_every: int = 100,
) -> List[Resolution]:
    from .normalize import normalize_domain, normalize_website

    resolutions: List[Resolution] = []
    total = len(companies)
    for idx, c in enumerate(companies, start=1):
        if c.domain:
            if progress_cb:
                progress_cb(idx, total)
            continue
        location = c.state_or_province or c.country
        res = resolve_domain(
            c.company_name, location, c.industry_hint,
            provider=provider, search_fn=search_fn, classify_fn=classify_fn,
        )
        resolutions.append(res)
        if res.chosen_domain and res.confidence in {"high", "medium"}:
            c.domain = normalize_domain(res.chosen_domain)
            if not c.website:
                c.website = normalize_website("", c.domain)
            tag = f"resolved_via={res.provider}"
            c.source = (c.source + " | " + tag).strip(" |")
        if progress_cb:
            progress_cb(idx, total)
        if checkpoint_cb and (idx % checkpoint_every == 0 or idx == total):
            try:
                checkpoint_cb(resolutions, companies)
            except Exception:
                pass
    return resolutions
