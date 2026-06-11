import json

from src.domain_resolver import (
    BLOCKED_DOMAINS,
    resolve_domain,
    resolve_missing_domains,
)
from src.models import Company


def _fake(response_dict):
    return lambda prompt, model: json.dumps(response_dict)


def test_resolves_corporate_domain():
    res = resolve_domain(
        "Cortes Laser SA",
        "Madrid",
        search_fn=_fake({
            "domain": "corteslaser.es",
            "url": "https://corteslaser.es/",
            "confidence": "high",
            "reason": "Página oficial",
        }),
    )
    assert res.chosen_domain == "corteslaser.es"
    assert res.confidence == "high"
    assert res.error == ""


def test_blocked_domain_is_rejected():
    res = resolve_domain(
        "Cortes Laser SA",
        "Madrid",
        search_fn=_fake({
            "domain": "linkedin.com",
            "url": "https://linkedin.com/company/x",
            "confidence": "high",
            "reason": "Perfil LinkedIn",
        }),
    )
    assert res.chosen_domain == ""
    assert res.confidence == "none"
    assert "linkedin.com" in BLOCKED_DOMAINS


def test_invalid_json_returns_error_free_none():
    res = resolve_domain(
        "Cortes Laser SA", "Madrid",
        search_fn=lambda p, m: "no json at all",
    )
    assert res.chosen_domain == ""
    assert res.confidence == "none"


def test_search_exception_is_reported():
    def boom(prompt, model):
        raise RuntimeError("api down")

    res = resolve_domain("X", "Y", search_fn=boom)
    assert res.error == "api down"
    assert res.chosen_domain == ""


def test_confidence_high_when_slug_matches_exact():
    res = resolve_domain(
        "Acme",
        "Madrid",
        search_fn=_fake({
            "domain": "acme.com", "url": "https://acme.com",
            "confidence": "medium", "reason": "",
        }),
    )
    # slug match upgrades model "medium" to "high"
    assert res.confidence == "high"


def test_skips_companies_with_domain():
    companies = [
        Company(company_name="Con dominio", domain="ya.es"),
        Company(company_name="Sin dominio", state_or_province="Madrid"),
    ]
    fake = _fake({
        "domain": "sindominio.com", "url": "https://sindominio.com",
        "confidence": "high", "reason": "",
    })
    resolutions = resolve_missing_domains(companies, search_fn=fake)
    assert len(resolutions) == 1
    assert resolutions[0].company_name == "Sin dominio"
    # Confident result fills in the domain
    assert companies[1].domain == "sindominio.com"
    assert companies[1].website.startswith("https://sindominio.com")
    assert "resolved_via=openai_web_search" in companies[1].source
    # Did not touch the company that already had a domain
    assert companies[0].domain == "ya.es"


def test_low_confidence_does_not_fill_domain():
    company = Company(company_name="Algo Generico", state_or_province="Sevilla")
    fake = _fake({
        "domain": "otracosa.com", "url": "https://otracosa.com",
        "confidence": "low", "reason": "no estoy seguro",
    })
    resolutions = resolve_missing_domains([company], search_fn=fake)
    # Resolution is recorded for auditing
    assert resolutions[0].chosen_domain == "otracosa.com"
    assert resolutions[0].confidence == "low"
    # But the company is left untouched, so it appears in targets_sin_email
    assert company.domain == ""
