from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

from .models import EnrichedEmail
from .normalize import normalize_email
from .scraper import ScrapeResult

OUTPUTS_DIR = Path("outputs")

BREVO_COLUMNS = [
    "EMAIL",
    "EMPRESA",
    "NOMBRE",
    "APELLIDO",
    "PROVINCIA",
    "CIUDAD",
    "TELEFONO",
    "WEB",
    "FUENTE_URL",
    "FUENTE_URLS_ALL",
    "TIPO_EMAIL",
    "CONFIANZA",
    "FUENTE_EMAIL",
    "FECHA_CAPTURA",
    "VERIFICATION_STATUS",
    "VERIFICATION_PROVIDER",
]

ALLOWED_CANDIDATE_PREFIXES = {
    "info",
    "contacto",
    "comercial",
    "ventas",
    "hola",
    "administracion",
}

_MC_EMAIL_COLS = {
    "email",
    "e-mail",
    "address",
    "email address",
    "emailaddress",
    "correo",
    "correo electronico",
}
_MC_STATUS_COLS = {
    "result",
    "status",
    "state",
    "verification status",
    "verification_status",
    "mailercheck status",
    "mailercheck_status",
}

_MC_STATUS_MAP = {
    "valid": "valid",
    "ok": "valid",
    "deliverable": "valid",
    "invalid": "invalid",
    "mailbox not found": "invalid",
    "mailbox_not_found": "invalid",
    "syntax error": "invalid",
    "syntax_error": "invalid",
    "disposable": "invalid",
    "undeliverable": "invalid",
    "rejected": "invalid",
    "risky": "risky",
    "catch-all": "risky",
    "catch all": "risky",
    "catch_all": "risky",
    "accept all": "risky",
    "accept_all": "risky",
    "accept-all": "risky",
    "unknown": "risky",
    "role-based": "risky",
    "role based": "risky",
    "role_based": "risky",
}


class MailerCheckFormatError(ValueError):
    """Raised when a MailerCheck CSV lacks an email or status column."""


def normalize_mc_status(raw: str) -> str:
    key = str(raw or "").strip().lower()
    if key in _MC_STATUS_MAP:
        return _MC_STATUS_MAP[key]
    # Unrecognized but present -> treat as risky (never silently valid).
    return "risky" if key else "risky"


def _detect_mc_columns(mc_df: pd.DataFrame) -> tuple[str, str]:
    cols = {str(c).lower().strip(): c for c in mc_df.columns}
    email_col = next((cols[k] for k in cols if k in _MC_EMAIL_COLS), None)
    status_col = next((cols[k] for k in cols if k in _MC_STATUS_COLS), None)
    if email_col is None:
        raise MailerCheckFormatError(
            "No se detectó la columna de email en el CSV de MailerCheck "
            "(esperado: email / Email Address / address)."
        )
    if status_col is None:
        raise MailerCheckFormatError(
            "No se detectó la columna de resultado/estado en el CSV de "
            "MailerCheck (esperado: result / status / verification_status)."
        )
    return email_col, status_col


def _row(e: EnrichedEmail) -> dict:
    c = e.company
    cls = e.classification
    return {
        "company_name": c.company_name,
        "target_domain": c.domain,
        "website": c.website,
        "email": e.match.email,
        "email_domain": e.match.email_domain,
        "source_url": e.match.source_url,
        "page_type": e.match.page_type,
        "match_type": e.match.match_type,
        "text_context": e.match.text_context,
        "state_or_province": c.state_or_province,
        "city": c.city,
        "phone": c.phone,
        "deterministic_score": e.deterministic_score,
        "deterministic_flag": e.deterministic_flag,
        "decision": e.final_decision,
        "email_type": cls.email_type if cls else "",
        "confidence": cls.confidence if cls else "",
        "brevo_recommended": e.brevo_recommended,
        "needs_ai_classification": e.needs_ai_classification,
        "candidate_mode": e.match.candidate_mode or (
            "none" if e.match.match_type != "generated_candidate" else ""
        ),
        "source_basis": e.match.source_basis,
        "must_verify": e.match.must_verify
        or e.match.match_type == "generated_candidate",
        "reason": cls.reason if cls else "",
        "evidence": cls.evidence if cls else "",
        "source": c.source,
    }


_PAGE_TYPE_RANK = {"contact": 0, "legal": 1, "privacy": 1, "home": 2}
_DECISION_RANK = {"accept": 0, "review": 1, "reject": 2}
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}
_PREFERRED_TYPES = {"generic_corporate", "personal_corporate"}


def _priority(e: EnrichedEmail) -> tuple:
    """Sort key for picking the representative row. Lower is better."""
    cls = e.classification
    confidence = cls.confidence if cls else "none"
    email_type = cls.email_type if cls else "none"
    return (
        _DECISION_RANK.get(e.final_decision, 3),
        0 if e.brevo_recommended else 1,
        _CONFIDENCE_RANK.get(confidence, 3),
        0 if email_type in _PREFERRED_TYPES else 1,
        -e.deterministic_score,
        _PAGE_TYPE_RANK.get(e.match.page_type, 3),
    )


def dedupe_by_email(
    enriched: List[EnrichedEmail],
) -> tuple[List[EnrichedEmail], Dict[str, List[str]]]:
    """Collapse to one representative EnrichedEmail per normalized email.

    The representative is the best row by `_priority` (decision, brevo
    recommendation, confidence, email_type, deterministic_score, page_type).
    The second return value maps the normalized email to every distinct URL
    where it appeared, so source_urls_all/source_count never lose provenance.
    """
    urls: Dict[str, List[str]] = {}
    for e in enriched:
        key = normalize_email(e.match.email)
        if e.match.source_url:
            bucket = urls.setdefault(key, [])
            if e.match.source_url not in bucket:
                bucket.append(e.match.source_url)

    chosen: Dict[str, EnrichedEmail] = {}
    for e in enriched:
        key = normalize_email(e.match.email)
        current = chosen.get(key)
        if current is None or _priority(e) < _priority(current):
            chosen[key] = e

    return list(chosen.values()), urls


def _deduped_rows(items: List[EnrichedEmail], urls: Dict[str, List[str]]) -> List[dict]:
    rows = []
    for e in items:
        key = normalize_email(e.match.email)
        all_urls = urls.get(key) or (
            [e.match.source_url] if e.match.source_url else []
        )
        row = _row(e)
        row["email"] = key
        row["source_urls_all"] = " | ".join(all_urls)
        row["source_count"] = len(all_urls)
        rows.append(row)
    return rows


def build_frames(enriched: List[EnrichedEmail]) -> Dict[str, pd.DataFrame]:
    non_generated = [
        e for e in enriched if e.match.match_type != "generated_candidate"
    ]
    generated = [
        e for e in enriched if e.match.match_type == "generated_candidate"
    ]

    reps, urls = dedupe_by_email(non_generated)
    reps.sort(key=_priority)
    rep_rows = _deduped_rows(reps, urls)
    public_df = pd.DataFrame(rep_rows)

    def by_decision(decision: str) -> pd.DataFrame:
        rows = [r for r in rep_rows if r["decision"] == decision]
        return pd.DataFrame(rows)

    cand_reps, cand_urls = dedupe_by_email(generated)
    candidates_df = pd.DataFrame(_deduped_rows(cand_reps, cand_urls))

    return {
        "emails_publicos_encontrados.csv": public_df,
        "emails_aceptados_para_mailercheck.csv": by_decision("accept"),
        "emails_review.csv": by_decision("review"),
        "emails_rechazados.csv": by_decision("reject"),
        "emails_genericos_candidatos_no_confirmados.csv": candidates_df,
    }


def targets_without_email(
    enriched: List[EnrichedEmail], all_companies, scrapes: List[ScrapeResult]
) -> pd.DataFrame:
    found = {e.company.company_name + "|" + e.company.domain for e in enriched}
    rows = []
    for c in all_companies:
        key = c.company_name + "|" + c.domain
        if key not in found:
            rows.append(
                {
                    "company_name": c.company_name,
                    "domain": c.domain,
                    "website": c.website,
                    "state_or_province": c.state_or_province,
                    "phone": c.phone,
                    "source": c.source,
                }
            )
    return pd.DataFrame(rows)


def _brevo_row(
    email: str,
    company,
    *,
    fuente_url: str,
    fuente_urls_all: str,
    tipo_email: str,
    confianza: str,
    fuente_email: str,
    verification_status: str,
    verification_provider: str,
    fecha: str,
) -> dict:
    return {
        "EMAIL": email,
        "EMPRESA": company.company_name,
        "NOMBRE": "",
        "APELLIDO": "",
        "PROVINCIA": company.state_or_province,
        "CIUDAD": company.city,
        "TELEFONO": company.phone,
        "WEB": company.website,
        "FUENTE_URL": fuente_url,
        "FUENTE_URLS_ALL": fuente_urls_all,
        "TIPO_EMAIL": tipo_email,
        "CONFIANZA": confianza,
        "FUENTE_EMAIL": fuente_email,
        "FECHA_CAPTURA": fecha,
        "VERIFICATION_STATUS": verification_status,
        "VERIFICATION_PROVIDER": verification_provider,
    }


def brevo_pre_verification(enriched: List[EnrichedEmail]) -> pd.DataFrame:
    today = datetime.now().strftime("%Y-%m-%d")
    non_generated = [
        e for e in enriched if e.match.match_type != "generated_candidate"
    ]
    items, urls = dedupe_by_email(non_generated)
    items.sort(key=_priority)
    rows = []
    for e in items:
        cls = e.classification
        key = normalize_email(e.match.email)
        all_urls = urls.get(key) or (
            [e.match.source_url] if e.match.source_url else []
        )
        rows.append(
            _brevo_row(
                key,
                e.company,
                fuente_url=e.match.source_url,
                fuente_urls_all=" | ".join(all_urls),
                tipo_email=cls.email_type if cls else "",
                confianza=cls.confidence if cls else "",
                fuente_email="publico_web_sin_verificar",
                verification_status="",
                verification_provider="",
                fecha=today,
            )
        )
    return pd.DataFrame(rows, columns=BREVO_COLUMNS)


def visited_urls_frame(scrapes: List[ScrapeResult]) -> pd.DataFrame:
    rows = []
    for s in scrapes:
        for p in s.pages:
            rows.append(
                {
                    "company_name": p.company_name,
                    "domain": p.domain,
                    "url": p.url,
                    "status_code": p.status_code,
                    "title": p.title,
                    "page_type": p.page_type,
                    "error": p.error,
                }
            )
    return pd.DataFrame(rows)


def errors_frame(scrapes: List[ScrapeResult]) -> pd.DataFrame:
    rows = []
    for s in scrapes:
        for p in s.pages:
            if p.error or (p.status_code and p.status_code >= 400):
                rows.append(
                    {
                        "company_name": p.company_name,
                        "url": p.url,
                        "status_code": p.status_code,
                        "error": p.error or f"http_{p.status_code}",
                    }
                )
    return pd.DataFrame(rows)


def raw_matches_frame(enriched: List[EnrichedEmail]) -> pd.DataFrame:
    return pd.DataFrame([_row(e) for e in enriched])


def _public_reps(enriched: List[EnrichedEmail]) -> List[EnrichedEmail]:
    non_generated = [
        e for e in enriched if e.match.match_type != "generated_candidate"
    ]
    reps, _ = dedupe_by_email(non_generated)
    return reps


def _candidate_reps(enriched: List[EnrichedEmail]) -> List[EnrichedEmail]:
    generated = [
        e for e in enriched if e.match.match_type == "generated_candidate"
    ]
    reps, _ = dedupe_by_email(generated)
    return reps


def mailercheck_public_emails(enriched: List[EnrichedEmail]) -> pd.DataFrame:
    """Single `email` column: only accepted public emails, deduplicated."""
    emails = {
        normalize_email(e.match.email)
        for e in _public_reps(enriched)
        if e.final_decision == "accept"
    }
    return pd.DataFrame({"email": sorted(e for e in emails if e)})


def mailercheck_candidate_emails(enriched: List[EnrichedEmail]) -> pd.DataFrame:
    """Single `email` column: only generic candidates, deduplicated."""
    emails = {
        normalize_email(e.match.email) for e in _candidate_reps(enriched)
    }
    return pd.DataFrame({"email": sorted(e for e in emails if e)})


def mailercheck_file(
    enriched: List[EnrichedEmail], include_candidates: bool = False
) -> pd.DataFrame:
    """Default: only accepted public emails. Candidates only on opt-in."""
    emails = {
        normalize_email(e.match.email)
        for e in _public_reps(enriched)
        if e.final_decision == "accept"
    }
    if include_candidates:
        emails |= {
            normalize_email(e.match.email) for e in _candidate_reps(enriched)
        }
    return pd.DataFrame({"email": sorted(e for e in emails if e)})


def create_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUTS_DIR / f"run_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def flush_partial(
    run_dir: Path,
    resolutions=None,
    scrapes=None,
    enriched=None,
    companies=None,
    stage: str = "",
) -> None:
    """Write whatever partial state we have to disk. Safe to call anytime."""
    try:
        if resolutions is not None:
            resolutions_frame(resolutions).to_csv(
                run_dir / "domain_resolutions.csv",
                index=False, encoding="utf-8-sig",
            )
        if scrapes is not None:
            visited_urls_frame(scrapes).to_csv(
                run_dir / "visited_urls.csv",
                index=False, encoding="utf-8-sig",
            )
            errors_frame(scrapes).to_csv(
                run_dir / "errors.csv",
                index=False, encoding="utf-8-sig",
            )
        if enriched is not None:
            raw_matches_frame(enriched).to_csv(
                run_dir / "raw_email_matches.csv",
                index=False, encoding="utf-8-sig",
            )
            for name, frame in build_frames(enriched).items():
                frame.to_csv(run_dir / name, index=False, encoding="utf-8-sig")
        if companies is not None:
            pd.DataFrame(
                [c.model_dump() for c in companies]
            ).to_csv(
                run_dir / "companies_state.csv",
                index=False, encoding="utf-8-sig",
            )
        (run_dir / "_status.json").write_text(
            json.dumps(
                {
                    "stage": stage,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "resolutions": 0 if resolutions is None else len(resolutions),
                    "scrapes": 0 if scrapes is None else len(scrapes),
                    "enriched": 0 if enriched is None else len(enriched),
                },
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        # Autosave is best-effort; never crash the pipeline because of it.
        pass


def resolutions_frame(resolutions) -> pd.DataFrame:
    rows = []
    for r in resolutions or []:
        rows.append(
            {
                "company_name": r.company_name,
                "query": r.query,
                "chosen_domain": r.chosen_domain,
                "chosen_url": r.chosen_url,
                "confidence": r.confidence,
                "reason": r.reason,
                "provider": r.provider,
                "error": r.error,
            }
        )
    return pd.DataFrame(rows)


def write_run(
    enriched: List[EnrichedEmail],
    all_companies,
    scrapes: List[ScrapeResult],
    run_config: dict,
    resolutions=None,
    run_dir: Path | None = None,
) -> Path:
    if run_dir is None:
        run_dir = create_run_dir()
    else:
        run_dir.mkdir(parents=True, exist_ok=True)

    for name, frame in build_frames(enriched).items():
        frame.to_csv(run_dir / name, index=False, encoding="utf-8-sig")

    targets_without_email(enriched, all_companies, scrapes).to_csv(
        run_dir / "targets_sin_email_encontrado.csv", index=False, encoding="utf-8-sig"
    )
    brevo_pre_verification(enriched).to_csv(
        run_dir / "brevo_import_pre_verification.csv",
        index=False,
        encoding="utf-8-sig",
    )
    visited_urls_frame(scrapes).to_csv(
        run_dir / "audit_log_urls_visitadas.csv", index=False, encoding="utf-8-sig"
    )
    visited_urls_frame(scrapes).to_csv(
        run_dir / "visited_urls.csv", index=False, encoding="utf-8-sig"
    )
    errors_frame(scrapes).to_csv(
        run_dir / "errors.csv", index=False, encoding="utf-8-sig"
    )
    raw_matches_frame(enriched).to_csv(
        run_dir / "raw_email_matches.csv", index=False, encoding="utf-8-sig"
    )
    mailercheck_file(enriched, include_candidates=False).to_csv(
        run_dir / "mailercheck_emails.csv", index=False, encoding="utf-8-sig"
    )
    mailercheck_public_emails(enriched).to_csv(
        run_dir / "mailercheck_public_emails.csv",
        index=False,
        encoding="utf-8-sig",
    )
    mailercheck_candidate_emails(enriched).to_csv(
        run_dir / "mailercheck_candidate_emails.csv",
        index=False,
        encoding="utf-8-sig",
    )
    resolutions_frame(resolutions).to_csv(
        run_dir / "domain_resolutions.csv", index=False, encoding="utf-8-sig"
    )
    (run_dir / "run_config.json").write_text(
        json.dumps(run_config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


def _public_row(e: EnrichedEmail, urls, status: str, today: str) -> dict:
    key = normalize_email(e.match.email)
    all_urls = urls.get(key) or ([e.match.source_url] if e.match.source_url else [])
    cls = e.classification
    return {
        "email": key,
        "company_name": e.company.company_name,
        "domain": e.company.domain,
        "website": e.company.website,
        "source_url": e.match.source_url,
        "source_urls_all": " | ".join(all_urls),
        "source_count": len(all_urls),
        "decision": e.final_decision,
        "email_type": cls.email_type if cls else "",
        "confidence": cls.confidence if cls else "",
        "reason": cls.reason if cls else "",
        "state_or_province": e.company.state_or_province,
        "city": e.company.city,
        "phone": e.company.phone,
        "verification_status": status,
        "verification_provider": "MailerCheck",
        "verification_date": today,
    }


def _candidate_row(e: EnrichedEmail, status: str, today: str) -> dict:
    key = normalize_email(e.match.email)
    prefix = key.split("@")[0]
    domain_match = e.match.email_domain.lower() == e.company.domain.lower()
    brevo_ok = (
        status == "valid"
        and domain_match
        and prefix in ALLOWED_CANDIDATE_PREFIXES
    )
    return {
        "email": key,
        "company_name": e.company.company_name,
        "domain": e.company.domain,
        "candidate_mode": e.match.candidate_mode,
        "source_basis": "generated_generic_pattern",
        "verification_status": status,
        "verification_provider": "MailerCheck",
        "verification_date": today,
        "confidence": "medium" if status == "valid" else "low",
        "FUENTE_EMAIL": "candidato_generico_verificado",
        "brevo_recommended": brevo_ok,
        "state_or_province": e.company.state_or_province,
        "city": e.company.city,
        "phone": e.company.phone,
        "website": e.company.website,
    }


def cross_mailercheck(
    enriched: List[EnrichedEmail],
    mc_df: pd.DataFrame,
    include_combined: bool = False,
) -> Dict[str, pd.DataFrame]:
    """Cross a MailerCheck export against public emails and candidates.

    Raises MailerCheckFormatError if email/status columns are not found.
    """
    email_col, status_col = _detect_mc_columns(mc_df)
    status_by_email: Dict[str, str] = {}
    for _, r in mc_df.iterrows():
        em = normalize_email(str(r[email_col]))
        if not em:
            continue
        st = normalize_mc_status(r[status_col])
        # valid beats risky beats invalid if the same email repeats.
        rank = {"valid": 0, "risky": 1, "invalid": 2}
        if em not in status_by_email or rank[st] < rank[status_by_email[em]]:
            status_by_email[em] = st

    non_generated = [
        e for e in enriched if e.match.match_type != "generated_candidate"
    ]
    pub_reps, pub_urls = dedupe_by_email(non_generated)
    pub_reps = [e for e in pub_reps if e.final_decision != "reject"]
    cand_reps = _candidate_reps(enriched)

    today = datetime.now().strftime("%Y-%m-%d")

    pub = {"valid": [], "invalid": [], "risky": []}
    for e in pub_reps:
        key = normalize_email(e.match.email)
        if key not in status_by_email:
            continue
        st = status_by_email[key]
        pub[st].append(_public_row(e, pub_urls, st, today))

    cand = {"valid": [], "invalid": [], "risky": []}
    for e in cand_reps:
        key = normalize_email(e.match.email)
        if key not in status_by_email:
            continue
        st = status_by_email[key]
        cand[st].append(_candidate_row(e, st, today))

    pub_company = {
        normalize_email(e.match.email): e.company for e in pub_reps
    }

    brevo_public = []
    seen_pub = set()
    for r in pub["valid"]:
        if r["email"] in seen_pub:
            continue
        seen_pub.add(r["email"])
        brevo_public.append(
            _brevo_row(
                r["email"],
                pub_company[r["email"]],
                fuente_url=r["source_url"],
                fuente_urls_all=r["source_urls_all"],
                tipo_email=r["email_type"],
                confianza=r["confidence"],
                fuente_email="publico_web_validado",
                verification_status="valid",
                verification_provider="MailerCheck",
                fecha=today,
            )
        )

    cand_company = {
        normalize_email(e.match.email): e.company for e in cand_reps
    }
    brevo_candidates = []
    seen_cand = set()
    for r in cand["valid"]:
        if not r["brevo_recommended"] or r["email"] in seen_cand:
            continue
        seen_cand.add(r["email"])
        brevo_candidates.append(
            _brevo_row(
                r["email"],
                cand_company[r["email"]],
                fuente_url="",
                fuente_urls_all="",
                tipo_email="generic_corporate",
                confianza="medium",
                fuente_email="candidato_generico_verificado",
                verification_status="valid",
                verification_provider="MailerCheck",
                fecha=today,
            )
        )

    brevo_pub_df = pd.DataFrame(brevo_public, columns=BREVO_COLUMNS)
    brevo_cand_df = pd.DataFrame(brevo_candidates, columns=BREVO_COLUMNS)

    if include_combined:
        public_emails = set(brevo_pub_df["EMAIL"]) if not brevo_pub_df.empty else set()
        extra = (
            brevo_cand_df[~brevo_cand_df["EMAIL"].isin(public_emails)]
            if not brevo_cand_df.empty
            else brevo_cand_df
        )
        combined = pd.concat([brevo_pub_df, extra], ignore_index=True)
    else:
        combined = pd.DataFrame(columns=BREVO_COLUMNS)

    return {
        "emails_publicos_validos_finales.csv": pd.DataFrame(pub["valid"]),
        "emails_publicos_invalidos_descartados.csv": pd.DataFrame(pub["invalid"]),
        "emails_publicos_risky_review.csv": pd.DataFrame(pub["risky"]),
        "candidatos_genericos_validos.csv": pd.DataFrame(cand["valid"]),
        "candidatos_genericos_invalidos.csv": pd.DataFrame(cand["invalid"]),
        "candidatos_genericos_risky_review.csv": pd.DataFrame(cand["risky"]),
        "brevo_import_public_validated.csv": brevo_pub_df,
        "brevo_import_candidates_verified.csv": brevo_cand_df,
        "brevo_import_final_combined.csv": combined,
    }
