from src.exporter import (
    brevo_pre_verification,
    build_frames,
    dedupe_by_email,
    raw_matches_frame,
)
from src.models import Company, EmailMatch, EnrichedEmail


def _e(email, url, page_type, score, decision="accept"):
    c = Company(company_name="Laser SL", domain="laser.es", website="https://laser.es")
    m = EmailMatch(
        company_name="Laser SL",
        target_domain="laser.es",
        email=email,
        email_domain="laser.es",
        source_url=url,
        page_type=page_type,
        match_type="exact_public_email",
    )
    return EnrichedEmail(
        company=c,
        match=m,
        deterministic_score=score,
        final_decision=decision,
        brevo_recommended=True,
    )


def test_dedupe_keeps_highest_score():
    items = [
        _e("info@laser.es", "https://laser.es/", "home", 4.0),
        _e("info@laser.es", "https://laser.es/contacto", "contact", 9.0),
    ]
    chosen, urls = dedupe_by_email(items)
    assert len(chosen) == 1
    assert chosen[0].deterministic_score == 9.0
    assert urls["info@laser.es"] == (
        "https://laser.es/ | https://laser.es/contacto"
    )


def test_dedupe_tiebreak_page_type():
    items = [
        _e("info@laser.es", "https://laser.es/", "home", 5.0),
        _e("info@laser.es", "https://laser.es/aviso-legal", "legal", 5.0),
        _e("info@laser.es", "https://laser.es/contacto", "contact", 5.0),
    ]
    chosen, _ = dedupe_by_email(items)
    assert len(chosen) == 1
    assert chosen[0].match.page_type == "contact"


def test_accepted_and_brevo_deduped_raw_not():
    items = [
        _e("info@laser.es", "https://laser.es/", "home", 4.0),
        _e("info@laser.es", "https://laser.es/contacto", "contact", 9.0),
    ]
    accepted = build_frames(items)["emails_aceptados_para_mailercheck.csv"]
    brevo = brevo_pre_verification(items)
    raw = raw_matches_frame(items)

    assert len(accepted) == 1
    assert "source_urls_all" in accepted.columns
    assert accepted.iloc[0]["source_urls_all"].count(" | ") == 1
    assert len(brevo) == 1
    assert "source_urls_all" in brevo.columns
    assert len(raw) == 2
