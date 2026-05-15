from __future__ import annotations

import json
from typing import Optional

from pydantic import ValidationError

from .config import get_settings
from .logger import get_logger
from .models import Classification, EmailMatch

logger = get_logger()

PROMPT_TEMPLATE = """You are classifying B2B contact emails for lawful business outreach in Spain/EU.

Target company: {company_name}
Target website: {website}
Target domain: {domain}
Province/region: {state_or_province}
Email found: {email}
Email domain: {email_domain}
Source URL: {source_url}
Page type: {page_type}
Text context around email:
{text_context}

Task:
Decide whether the email is clearly linked to the target company and suitable to send to an email verification tool before importing into Brevo.

Rules:
- Do not guess.
- Do not invent facts.
- Use only the provided source URL and text context.
- Prefer generic corporate emails such as info@, contacto@, comercial@, ventas@, administracion@, hola@ when they are clearly published by the target company.
- Personal corporate emails are acceptable only if clearly shown as company contacts.
- Free emails such as Gmail, Hotmail, Outlook or Yahoo must be low or medium confidence unless clearly used as the official company contact.
- Reject emails belonging to web designers, SEO agencies, hosting providers, directories, marketplaces, analytics tools, unrelated suppliers or third-party platforms.
- Reject emails from another company with a similar name.
- If the source URL is the company's own domain and the email domain matches the target domain, confidence is usually high unless context indicates otherwise.
- If the source URL is a legal notice or privacy policy and the email is presented as contact/controller/company contact, confidence is high.
- If uncertain, choose review, not accept.

Return only valid JSON:
{{
  "decision": "accept|review|reject",
  "email_type": "generic_corporate|personal_corporate|personal_free_email|third_party|web_designer_or_provider|unrelated|none",
  "confidence": "high|medium|low|none",
  "brevo_recommended": true/false,
  "reason": "brief explanation",
  "evidence": "short quote or description of the evidence"
}}"""

REPAIR_SUFFIX = (
    "\n\nYour previous answer was not valid JSON matching the schema. "
    "Return ONLY the JSON object, no markdown, no commentary."
)


def _build_prompt(match: EmailMatch, website: str, province: str) -> str:
    return PROMPT_TEMPLATE.format(
        company_name=match.company_name,
        website=website,
        domain=match.target_domain,
        state_or_province=province,
        email=match.email,
        email_domain=match.email_domain,
        source_url=match.source_url or "(none - generated candidate)",
        page_type=match.page_type,
        text_context=(match.text_context or "")[:1500],
    )


def _parse(content: str) -> Optional[Classification]:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content[content.find("{") :]
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(content[start : end + 1])
        return Classification.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Classification parse failed: %s", exc)
        return None


def _pick_model(match: EmailMatch, deterministic_score: float) -> str:
    settings = get_settings()
    uncertain = -1.0 < deterministic_score < 5.0 or match.email_domain != match.target_domain
    return settings.openai_model_strong if uncertain else settings.openai_model_fast


def classify(
    match: EmailMatch, website: str, province: str, deterministic_score: float
) -> Optional[Classification]:
    settings = get_settings()
    if not settings.openai_enabled:
        return None

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    model = _pick_model(match, deterministic_score)
    prompt = _build_prompt(match, website, province)

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 - SDK raises many error types
            logger.error("OpenAI call failed (%s): %s", model, exc)
            return None
        parsed = _parse(content)
        if parsed is not None:
            return parsed
        prompt = prompt + REPAIR_SUFFIX

    logger.warning("Falling back to review for %s", match.email)
    return Classification(
        decision="review",
        email_type="none",
        confidence="none",
        brevo_recommended=False,
        reason="invalid_model_response",
        evidence="",
    )
