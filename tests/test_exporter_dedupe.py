from src.exporter import (
    brevo_pre_verification,
    build_frames,
    dedupe_by_email,
    mailercheck_file,
    raw_matches_frame,
)
from src.models import Classification, Company, EmailMatch, EnrichedEmail


def _e(email, url, page_type, score, decision="accept", brevo=True, conf="high"):
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
        brevo_recommended=brevo,
        classification=Classification(
            decision=decision,
            email_type="generic_corporate",
            confidence=conf,
            brevo_recommended=brevo,
            reason="r",
            evidence="ev",
        ),
    )


def test_same_email_three_pages_collapses_to_one():
    items = [
        _e("info@laser.es", "https://laser.es/", "home", 4.0),
        _e("info@laser.es", "https://laser.es/contacto", "contact", 9.0),
        _e("info@laser.es", "https://laser.es/aviso-legal", "legal", 6.0),
    ]
    df = build_frames(items)["emails_aceptados_para_mailercheck.csv"]
    assert len(df) == 1
    row = df.iloc[0]
    assert row["source_count"] == 3
    assert row["source_urls_all"].count(" | ") == 2
    assert "https://laser.es/contacto" in row["source_urls_all"]


def test_accept_wins_over_review():
    items = [
        _e("info@laser.es", "https://laser.es/contacto", "contact", 5.0,
           decision="review", brevo=False, conf="low"),
        _e("info@laser.es", "https://laser.es/", "home", 3.0,
           decision="accept", brevo=True, conf="high"),
    ]
    frames = build_frames(items)
    accepted = frames["emails_aceptados_para_mailercheck.csv"]
    review = frames["emails_review.csv"]
    assert len(accepted) == 1
    assert accepted.iloc[0]["decision"] == "accept"
    assert len(review) == 0


def test_raw_keeps_all_matches():
    items = [
        _e("info@laser.es", "https://laser.es/", "home", 4.0),
        _e("info@laser.es", "https://laser.es/contacto", "contact", 9.0),
    ]
    raw = raw_matches_frame(items)
    assert len(raw) == 2


def test_mailercheck_emails_unique():
    items = [
        _e("info@laser.es", "https://laser.es/", "home", 4.0),
        _e("INFO@laser.es ", "https://laser.es/contacto", "contact", 9.0),
        _e("ventas@laser.es", "https://laser.es/contacto", "contact", 8.0),
    ]
    mc = mailercheck_file(items, include_candidates=False)
    assert list(mc["email"]) == ["info@laser.es", "ventas@laser.es"]
    assert mc["email"].is_unique


def test_brevo_pre_verification_unique():
    items = [
        _e("info@laser.es", "https://laser.es/", "home", 4.0),
        _e("info@laser.es", "https://laser.es/contacto", "contact", 9.0),
        _e("ventas@laser.es", "https://laser.es/contacto", "contact", 8.0),
    ]
    brevo = brevo_pre_verification(items)
    assert brevo["EMAIL"].is_unique
    assert len(brevo) == 2
    assert "FUENTE_URLS_ALL" in brevo.columns
    assert "FUENTE_EMAIL" in brevo.columns


def test_email_normalized_in_dedupe_key():
    items = [
        _e("Info@Laser.es", "https://laser.es/", "home", 4.0),
        _e("info@laser.es", "https://laser.es/contacto", "contact", 9.0),
    ]
    reps, urls = dedupe_by_email(items)
    assert len(reps) == 1
    assert urls["info@laser.es"] == [
        "https://laser.es/",
        "https://laser.es/contacto",
    ]
