from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Decision = Literal["accept", "review", "reject"]
EmailType = Literal[
    "generic_corporate",
    "personal_corporate",
    "personal_free_email",
    "third_party",
    "web_designer_or_provider",
    "unrelated",
    "none",
]
Confidence = Literal["high", "medium", "low", "none"]
MatchType = Literal[
    "exact_public_email",
    "obfuscated_public_email",
    "mailto",
    "generated_candidate",
]
CandidateMode = Literal["none", "conservative", "standard", "broad"]


class Company(BaseModel):
    company_name: str = ""
    website: str = ""
    domain: str = ""
    country: str = ""
    state_or_province: str = ""
    city: str = ""
    address: str = ""
    phone: str = ""
    industry_hint: str = ""
    enrichment_priority: str = ""
    search_query: str = ""
    source: str = ""
    source_rows: str = ""


class VisitedURL(BaseModel):
    company_name: str
    domain: str
    url: str
    status_code: int = 0
    title: str = ""
    error: str = ""


class EmailMatch(BaseModel):
    company_name: str
    target_domain: str
    email: str
    email_domain: str
    source_url: str
    page_type: str
    text_context: str = ""
    match_type: MatchType
    candidate_mode: str = ""
    source_basis: str = "public_scrape"
    must_verify: bool = False


class Classification(BaseModel):
    decision: Decision
    email_type: EmailType
    confidence: Confidence
    brevo_recommended: bool
    reason: str = ""
    evidence: str = ""


class EnrichedEmail(BaseModel):
    company: Company
    match: EmailMatch
    deterministic_score: float = 0.0
    deterministic_flag: str = ""
    classification: Optional[Classification] = None
    final_decision: Decision = "review"
    brevo_recommended: bool = False
    needs_ai_classification: bool = False
