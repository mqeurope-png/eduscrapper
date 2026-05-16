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


def brevo_pre_verification(enriched: List[EnrichedEmail]) -> pd.DataFrame:
    today = datetime.now().strftime("%Y-%m-%d")
    non_generated = [
        e for e in enriched if e.match.match_type != "generated_candidate"
    ]
    items, urls = dedupe_by_email(non_generated)
    items.sort(key=_priority)
    rows = []
    for e in items:
        c = e.company
        cls = e.classification
        key = normalize_email(e.match.email)
        all_urls = urls.get(key) or (
            [e.match.source_url] if e.match.source_url else []
        )
        rows.append(
            {
                "EMAIL": key,
                "EMPRESA": c.company_name,
                "NOMBRE": "",
                "APELLIDO": "",
                "PROVINCIA": c.state_or_province,
                "CIUDAD": c.city,
                "TELEFONO": c.phone,
                "WEB": c.website,
                "FUENTE_URL": e.match.source_url,
                "source_urls_all": " | ".join(all_urls),
                "source_count": len(all_urls),
                "TIPO_EMAIL": cls.email_type if cls else "",
                "CONFIANZA": cls.confidence if cls else "",
                "REASON": cls.reason if cls else "",
                "EVIDENCE": cls.evidence if cls else "",
                "FECHA_CAPTURA": today,
            }
        )
    return pd.DataFrame(rows)


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


def mailercheck_file(
    enriched: List[EnrichedEmail], include_candidates: bool
) -> pd.DataFrame:
    non_generated = [
        e for e in enriched if e.match.match_type != "generated_candidate"
    ]
    reps, _ = dedupe_by_email(non_generated)
    emails = {
        normalize_email(e.match.email)
        for e in reps
        if e.final_decision != "reject"
    }
    if include_candidates:
        generated = [
            e for e in enriched if e.match.match_type == "generated_candidate"
        ]
        cand_reps, _ = dedupe_by_email(generated)
        emails |= {normalize_email(e.match.email) for e in cand_reps}
    return pd.DataFrame({"email": sorted(e for e in emails if e)})


def write_run(
    enriched: List[EnrichedEmail],
    all_companies,
    scrapes: List[ScrapeResult],
    run_config: dict,
) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUTS_DIR / f"run_{stamp}"
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
    (run_dir / "run_config.json").write_text(
        json.dumps(run_config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


def cross_mailercheck(
    enriched: List[EnrichedEmail], mc_df: pd.DataFrame
) -> Dict[str, pd.DataFrame]:
    """Cross results with a MailerCheck export by email."""
    cols = {c.lower().strip(): c for c in mc_df.columns}
    email_col = cols.get("email") or list(mc_df.columns)[0]
    status_col = (
        cols.get("status")
        or cols.get("result")
        or cols.get("mailercheck_status")
        or None
    )
    mc = mc_df.copy()
    mc["_email"] = mc[email_col].astype(str).str.strip().str.lower()
    if status_col:
        mc["_status"] = mc[status_col].astype(str).str.strip().str.lower()
    else:
        mc["_status"] = "valid"

    valid_emails = set(
        mc.loc[mc["_status"].isin({"valid", "ok", "deliverable"}), "_email"]
    )

    base = raw_matches_frame(enriched)
    if base.empty:
        empty = pd.DataFrame()
        return {
            "emails_validos_finales.csv": empty,
            "emails_invalidos_descartados.csv": empty,
            "brevo_import_final.csv": empty,
        }
    base["_email"] = base["email"].astype(str).str.strip().str.lower()
    valid = base[base["_email"].isin(valid_emails)].reset_index(drop=True)
    invalid = base[~base["_email"].isin(valid_emails)].reset_index(drop=True)

    today = datetime.now().strftime("%Y-%m-%d")
    brevo_rows = []
    for _, r in valid.iterrows():
        brevo_rows.append(
            {
                "EMAIL": r["email"],
                "EMPRESA": r["company_name"],
                "NOMBRE": "",
                "APELLIDO": "",
                "PROVINCIA": r.get("state_or_province", ""),
                "CIUDAD": r.get("city", ""),
                "TELEFONO": r.get("phone", ""),
                "WEB": r.get("website", ""),
                "FUENTE_URL": r.get("source_url", ""),
                "TIPO_EMAIL": r.get("email_type", ""),
                "CONFIANZA": r.get("confidence", ""),
                "FECHA_CAPTURA": today,
            }
        )
    return {
        "emails_validos_finales.csv": valid.drop(columns=["_email"]),
        "emails_invalidos_descartados.csv": invalid.drop(columns=["_email"]),
        "brevo_import_final.csv": pd.DataFrame(brevo_rows),
    }
