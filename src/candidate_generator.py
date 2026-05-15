from __future__ import annotations

from typing import List

from .models import Company, EmailMatch

GENERIC_PREFIXES = [
    "info",
    "contacto",
    "comercial",
    "ventas",
    "administracion",
    "hola",
]


def generate_candidates(company: Company) -> List[EmailMatch]:
    if not company.domain:
        return []
    candidates: List[EmailMatch] = []
    for prefix in GENERIC_PREFIXES:
        email = f"{prefix}@{company.domain}".lower()
        candidates.append(
            EmailMatch(
                company_name=company.company_name,
                target_domain=company.domain,
                email=email,
                email_domain=company.domain.lower(),
                source_url="",
                page_type="generated",
                text_context="candidate_only not_publicly_found must_verify",
                match_type="generated_candidate",
            )
        )
    return candidates
