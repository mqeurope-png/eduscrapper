import pandas as pd

from src.candidate_generator import generate_candidates
from src.exporter import (
    build_frames,
    cross_mailercheck,
    mailercheck_candidate_emails,
    mailercheck_file,
)
from src.models import Classification, Company, EmailMatch, EnrichedEmail
from src.pipeline import _enrich_match


def _company(name="Laser SL", domain="laser.es"):
    return Company(
        company_name=name, domain=domain, website=f"https://{domain}",
        state_or_province="Madrid", city="Madrid", phone="912345678",
    )


def _public(email, decision="accept", url="https://laser.es/contacto", company=None):
    c = company or _company()
    m = EmailMatch(
        company_name=c.company_name, target_domain=c.domain, email=email,
        email_domain=email.split("@")[1], source_url=url, page_type="contact",
        match_type="exact_public_email",
    )
    return EnrichedEmail(
        company=c, match=m, deterministic_score=8.0, final_decision=decision,
        brevo_recommended=(decision == "accept"),
        classification=Classification(
            decision=decision, email_type="generic_corporate",
            confidence="high" if decision == "accept" else "low",
            brevo_recommended=(decision == "accept"), reason="r", evidence="e",
        ),
    )


# ---- candidate modes -------------------------------------------------------

def test_mode_none_no_candidates():
    assert generate_candidates(_company(), "none") == []


def test_mode_conservative_two():
    cs = generate_candidates(_company(), "conservative")
    assert [m.email for m in cs] == ["info@laser.es", "contacto@laser.es"]
    assert all(m.candidate_mode == "conservative" for m in cs)
    assert all(m.source_basis == "generated_generic_pattern" for m in cs)
    assert all(m.must_verify for m in cs)


def test_mode_standard_three():
    cs = generate_candidates(_company(), "standard")
    assert [m.email for m in cs] == [
        "info@laser.es", "contacto@laser.es", "comercial@laser.es"
    ]


def test_mode_broad_six():
    cs = generate_candidates(_company(), "broad")
    assert len(cs) == 6


def test_no_candidates_for_free_domain():
    assert generate_candidates(_company(domain="gmail.com"), "broad") == []


# ---- pipeline gating (simulated, no network) -------------------------------

def _run_with(matches_per_company, mode, with_review):
    """Mimic the candidate-gating logic of run_pipeline without scraping."""
    from src.candidate_generator import generate_candidates as gen

    enriched = []
    accepted, review = set(), set()
    for company, items in matches_per_company:
        for e in items:
            enriched.append(e)
            k = company.company_name + "|" + company.domain
            if e.final_decision == "accept":
                accepted.add(k)
            elif e.final_decision == "review":
                review.add(k)
    for company, _ in matches_per_company:
        k = company.company_name + "|" + company.domain
        if k in accepted:
            continue
        if k in review and not with_review:
            continue
        for cand in gen(company, mode):
            enriched.append(_enrich_match(cand, company, use_ai=False))
    return enriched


def test_no_candidates_when_accepted_public_exists():
    c = _company()
    enriched = _run_with([(c, [_public("info@laser.es", "accept", company=c)])],
                         "conservative", with_review=False)
    cand = [e for e in enriched if e.match.match_type == "generated_candidate"]
    assert cand == []


def test_no_candidates_when_only_review_default():
    c = _company()
    enriched = _run_with([(c, [_public("info@laser.es", "review", company=c)])],
                         "conservative", with_review=False)
    cand = [e for e in enriched if e.match.match_type == "generated_candidate"]
    assert cand == []


def test_candidates_when_review_and_optin():
    c = _company()
    enriched = _run_with([(c, [_public("info@laser.es", "review", company=c)])],
                         "conservative", with_review=True)
    cand = [e for e in enriched if e.match.match_type == "generated_candidate"]
    assert len(cand) == 2


def test_candidates_separated_from_public():
    c = _company()
    enriched = _run_with([(c, [_public("ventas@laser.es", "accept", company=c)]),
                          (_company("Otra", "otra.es"), [])],
                         "conservative", with_review=False)
    frames = build_frames(enriched)
    pub = frames["emails_publicos_encontrados.csv"]
    cands = frames["emails_genericos_candidatos_no_confirmados.csv"]
    assert "generated_candidate" not in set(pub["match_type"])
    assert set(cands["match_type"]) == {"generated_candidate"}
    assert len(cands) == 2  # info@ + contacto@ for otra.es


# ---- mailercheck_emails default behaviour ----------------------------------

def test_mailercheck_default_excludes_candidates():
    c = _company("Otra", "otra.es")
    enriched = _run_with([(c, [])], "conservative", with_review=False)
    enriched.append(_public("info@laser.es", "accept"))
    default = mailercheck_file(enriched)
    assert "info@otra.es" not in set(default["email"])
    assert "info@laser.es" in set(default["email"])


def test_mailercheck_includes_candidates_on_optin():
    c = _company("Otra", "otra.es")
    enriched = _run_with([(c, [])], "conservative", with_review=False)
    inc = mailercheck_file(enriched, include_candidates=True)
    assert "info@otra.es" in set(inc["email"])
    assert set(mailercheck_candidate_emails(enriched)["email"]) == {
        "info@otra.es", "contacto@otra.es"
    }


# ---- MailerCheck import ----------------------------------------------------

def _mc(rows):
    return pd.DataFrame(rows)


def test_mailercheck_format_error():
    import pytest

    from src.exporter import MailerCheckFormatError

    with pytest.raises(MailerCheckFormatError):
        cross_mailercheck([_public("info@laser.es")], _mc([{"foo": "bar"}]))


def test_import_separates_public_states():
    enriched = [
        _public("a@laser.es", "accept"),
        _public("b@laser.es", "accept"),
        _public("c@laser.es", "accept"),
    ]
    mc = _mc([
        {"Email Address": "a@laser.es", "Result": "Valid"},
        {"Email Address": "b@laser.es", "Result": "Mailbox not found"},
        {"Email Address": "c@laser.es", "Result": "Catch-all"},
    ])
    r = cross_mailercheck(enriched, mc)
    assert list(r["emails_publicos_validos_finales.csv"]["email"]) == ["a@laser.es"]
    assert list(r["emails_publicos_invalidos_descartados.csv"]["email"]) == [
        "b@laser.es"
    ]
    assert list(r["emails_publicos_risky_review.csv"]["email"]) == ["c@laser.es"]


def test_import_separates_candidates_and_brevo_rules():
    c = _company("Otra", "otra.es")
    enriched = _run_with([(c, [])], "broad", with_review=False)
    mc = _mc([
        {"email": "info@otra.es", "status": "Valid"},
        {"email": "contacto@otra.es", "status": "Invalid"},
        {"email": "comercial@otra.es", "status": "Unknown"},
    ])
    r = cross_mailercheck(enriched, mc)
    assert list(r["candidatos_genericos_validos.csv"]["email"]) == ["info@otra.es"]
    assert list(r["candidatos_genericos_invalidos.csv"]["email"]) == [
        "contacto@otra.es"
    ]
    assert list(r["candidatos_genericos_risky_review.csv"]["email"]) == [
        "comercial@otra.es"
    ]
    bc = r["brevo_import_candidates_verified.csv"]
    assert list(bc["EMAIL"]) == ["info@otra.es"]
    assert set(bc["FUENTE_EMAIL"]) == {"candidato_generico_verificado"}


def test_brevo_public_only_valid():
    enriched = [_public("a@laser.es", "accept"), _public("b@laser.es", "accept")]
    mc = _mc([
        {"email": "a@laser.es", "result": "valid"},
        {"email": "b@laser.es", "result": "invalid"},
    ])
    r = cross_mailercheck(enriched, mc)
    bp = r["brevo_import_public_validated.csv"]
    assert list(bp["EMAIL"]) == ["a@laser.es"]
    assert set(bp["FUENTE_EMAIL"]) == {"publico_web_validado"}


def test_combined_empty_unless_optin():
    c = _company("Otra", "otra.es")
    enriched = _run_with([(c, [])], "conservative", with_review=False)
    enriched.append(_public("a@laser.es", "accept"))
    mc = _mc([
        {"email": "a@laser.es", "result": "valid"},
        {"email": "info@otra.es", "result": "valid"},
    ])
    off = cross_mailercheck(enriched, mc, include_combined=False)
    assert off["brevo_import_final_combined.csv"].empty
    on = cross_mailercheck(enriched, mc, include_combined=True)
    assert len(on["brevo_import_final_combined.csv"]) == 2


def test_public_wins_over_candidate_in_combined():
    c = _company("Laser SL", "laser.es")
    # public info@laser.es accepted + candidate info@laser.es would collide
    enriched = [_public("info@laser.es", "accept", company=c)]
    enriched += [
        _enrich_match(m, c, use_ai=False)
        for m in generate_candidates(c, "conservative")
    ]
    mc = _mc([
        {"email": "info@laser.es", "result": "valid"},
        {"email": "contacto@laser.es", "result": "valid"},
    ])
    on = cross_mailercheck(enriched, mc, include_combined=True)
    combined = on["brevo_import_final_combined.csv"]
    info_rows = combined[combined["EMAIL"] == "info@laser.es"]
    assert len(info_rows) == 1
    assert info_rows.iloc[0]["FUENTE_EMAIL"] == "publico_web_validado"
