from src.normalize import (
    dedupe_key,
    normalize_domain,
    normalize_phone,
    normalize_province,
    normalize_website,
)


def test_normalize_domain_from_url():
    assert normalize_domain("", "https://www.laser-corte.es/contacto") == "laser-corte.es"


def test_normalize_domain_from_bare_domain():
    assert normalize_domain("WWW.Laser.ES") == "laser.es"


def test_normalize_domain_subdomain():
    assert normalize_domain("", "http://shop.empresa.com") == "empresa.com"


def test_website_from_domain():
    assert normalize_website("", "laser.es") == "https://laser.es"


def test_website_adds_scheme():
    assert normalize_website("laser.es").startswith("https://")


def test_phone_spanish_default_cc():
    assert normalize_phone("912 345 678") == "+34912345678"


def test_phone_keeps_international():
    assert normalize_phone("+33 1 23 45 67 89") == "+33123456789"


def test_phone_empty():
    assert normalize_phone("") == ""


def test_province_accents():
    assert normalize_province("malaga") == "Málaga"
    assert normalize_province("a coruna") == "A Coruña"


def test_dedupe_key_stable():
    a = dedupe_key("Laser SL", "laser.es")
    b = dedupe_key("laser sl", "https://laser.es")
    assert a == b
