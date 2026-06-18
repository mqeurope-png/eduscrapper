from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .candidate_generator import generate_candidates
from .classifier import classify
from .config import get_settings
from .domain_resolver import Resolution, resolve_missing_domains
from .email_extractor import extract_from_scrape
from .exporter import flush_partial
from .models import Classification, Company, EnrichedEmail
from .scoring import deterministic_decision, score_match
from .scraper import ScrapeResult, scrape_companies


def _enrich_match(match, company: Company, use_ai: bool) -> EnrichedEmail:
    score, flag = score_match(match)
    enriched = EnrichedEmail(
        company=company,
        match=match,
        deterministic_score=score,
        deterministic_flag=flag,
    )

    classification: Classification | None = None
    settings = get_settings()
    if use_ai and settings.openai_enabled:
        classification = classify(
            match, company.website, company.state_or_province, score
        )

    if classification is not None:
        enriched.classification = classification
        enriched.final_decision = classification.decision
        enriched.brevo_recommended = classification.brevo_recommended
    else:
        decision, brevo = deterministic_decision(score, flag)
        enriched.final_decision = decision
        enriched.brevo_recommended = brevo
        enriched.needs_ai_classification = use_ai is False or (
            not settings.openai_enabled
        )

    if match.match_type == "generated_candidate":
        enriched.brevo_recommended = False
        if enriched.final_decision == "accept":
            enriched.final_decision = "review"

    return enriched


def run_pipeline(
    companies: List[Company],
    use_ai: bool,
    candidate_mode: str = "conservative",
    candidates_with_review: bool = False,
    auto_resolve_domains: bool = False,
    resolver_provider: str = "openai",
    scrape_progress=None,
    classify_progress=None,
    resolve_progress=None,
    run_dir: Optional[Path] = None,
    checkpoint_every: int = 200,
) -> tuple[List[EnrichedEmail], List[ScrapeResult], List[Resolution]]:
    resolutions: List[Resolution] = []
    resolver_ckpt = None
    if run_dir is not None:
        def resolver_ckpt(res_list, comps):
            flush_partial(
                run_dir, resolutions=res_list, companies=comps,
                stage="resolving_domains",
            )

    if auto_resolve_domains:
        s = get_settings()
        ok = s.openai_enabled and (
            resolver_provider != "brave" or s.brave_enabled
        )
        if ok:
            resolutions = resolve_missing_domains(
                companies,
                progress_cb=resolve_progress,
                provider=resolver_provider,
                checkpoint_cb=resolver_ckpt,
            )

    scrape_ckpt = None
    if run_dir is not None:
        def scrape_ckpt(partial_scrapes):
            flush_partial(
                run_dir, resolutions=resolutions, scrapes=partial_scrapes,
                stage="scraping",
            )

    scrapes = scrape_companies(
        companies, progress_cb=scrape_progress, checkpoint_cb=scrape_ckpt,
        checkpoint_every=checkpoint_every,
    )

    enriched: List[EnrichedEmail] = []
    companies_with_accepted_public: set[str] = set()
    companies_with_review_public: set[str] = set()

    settings = get_settings()
    cap = max(1, settings.max_emails_classified_per_company)
    total = len(scrapes)
    for idx, scrape in enumerate(scrapes, start=1):
        matches = extract_from_scrape(scrape)
        # A page can dump dozens of emails (legal notices, staff lists, footer
        # widgets). Classifying every single one with OpenAI is slow and
        # rarely useful: prioritise contact/legal/privacy/about pages and the
        # most informative candidates so the obvious winners get scored
        # while we don't burn the budget on the long tail.
        target = (scrape.company.domain or "").lower()
        page_rank = {"contact": 0, "legal": 1, "privacy": 1, "about": 2, "home": 3}

        def _match_priority(m, target=target, page_rank=page_rank):
            same_domain = 0 if (target and m.email_domain.lower() == target) else 1
            local = m.email.split("@", 1)[0].lower()
            generic_priority = (
                0 if local in {"info", "contact", "contacto",
                               "comercial", "ventas", "hola",
                               "hello", "administracion"} else 1
            )
            page_priority = page_rank.get(m.page_type, 4)
            return (same_domain, generic_priority, page_priority)

        matches.sort(key=_match_priority)
        if len(matches) > cap:
            matches = matches[:cap]
        for match in matches:
            item = _enrich_match(match, scrape.company, use_ai)
            enriched.append(item)
            if match.match_type == "generated_candidate":
                continue
            key = scrape.company.company_name + "|" + scrape.company.domain
            if item.final_decision == "accept":
                companies_with_accepted_public.add(key)
            elif item.final_decision == "review":
                companies_with_review_public.add(key)
        if classify_progress:
            classify_progress(idx, total)
        if run_dir is not None and (idx % checkpoint_every == 0 or idx == total):
            flush_partial(
                run_dir, resolutions=resolutions, scrapes=scrapes,
                enriched=enriched, stage="classifying",
            )

    # Candidates: corporate domain, no accepted public email, and (unless the
    # user opted in) no public emails sitting in review for that company.
    for scrape in scrapes:
        company = scrape.company
        key = company.company_name + "|" + company.domain
        if not company.domain or key in companies_with_accepted_public:
            continue
        if key in companies_with_review_public and not candidates_with_review:
            continue
        for cand in generate_candidates(company, candidate_mode):
            enriched.append(_enrich_match(cand, company, use_ai=False))

    return enriched, scrapes, resolutions
