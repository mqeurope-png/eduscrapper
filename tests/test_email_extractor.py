from src.email_extractor import extract_from_scrape
from src.models import Company
from src.scraper import PageResult, ScrapeResult


def _scrape(text: str = "", html: str = "", page_type: str = "contact") -> ScrapeResult:
    company = Company(company_name="Laser SL", domain="laser.es", website="https://laser.es")
    page = PageResult(
        company_name="Laser SL",
        domain="laser.es",
        url="https://laser.es/contacto",
        status_code=200,
        text=text,
        html=html,
        page_type=page_type,
    )
    return ScrapeResult(company=company, pages=[page])


def test_plain_email():
    matches = extract_from_scrape(_scrape(text="Contacto: info@laser.es"))
    assert len(matches) == 1
    assert matches[0].email == "info@laser.es"
    assert matches[0].email_domain == "laser.es"
    assert matches[0].match_type == "exact_public_email"


def test_obfuscated_at_variants():
    for raw in [
        "ventas [at] laser.es",
        "ventas(at)laser.es",
        "ventas[@]laser.es",
    ]:
        matches = extract_from_scrape(_scrape(text=f"Escribe a {raw}"))
        assert any(m.email == "ventas@laser.es" for m in matches), raw


def test_obfuscated_words():
    matches = extract_from_scrape(
        _scrape(text="info arroba laser punto es para contactar")
    )
    assert any(m.email == "info@laser.es" for m in matches)


def test_mailto_from_html():
    html = '<a href="mailto:comercial@laser.es">Escríbenos</a>'
    matches = extract_from_scrape(_scrape(html=html, text="Escríbenos"))
    assert any(
        m.email == "comercial@laser.es" and m.match_type == "mailto" for m in matches
    )


def test_example_domains_filtered():
    matches = extract_from_scrape(_scrape(text="Demo: user@example.com"))
    assert matches == []


def test_trailing_punctuation_stripped():
    matches = extract_from_scrape(_scrape(text="Contacto (info@laser.es)."))
    assert matches[0].email == "info@laser.es"


def test_dedupe_same_url_email():
    matches = extract_from_scrape(
        _scrape(text="info@laser.es ... y otra vez info@laser.es")
    )
    assert len(matches) == 1
