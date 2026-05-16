from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

from .models import EnrichedEmail
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


def _tiebreak_rank(e: EnrichedEmail) -> tuple[float, int]:
    # Lower is better: highest score first, then page_type priority.
    return (-e.deterministic_score, _PAGE_TYPE_RANK.get(e.match.page_type, 3))


def dedupe_by_email(
    enriched: List[EnrichedEmail], predicate=None
) -> tuple[List[EnrichedEmail], Dict[str, str]]:
    """Pick one representative EnrichedEmail per email and the joined URLs.

    The representative has the highest deterministic_score; ties are broken
    by page_type (contact > legal/privacy > home > other). source_urls_all
    aggregates every distinct URL where that email appeared, regardless of
    the predicate, so provenance is never lost.
    """
    urls: Dict[str, List[str]] = {}
    for e in enriched:
        if e.match.source_url:
            bucket = urls.setdefault(e.match.email, [])
            if e.match.source_url not in bucket:
                bucket.append(e.match.source_url)

    chosen: Dict[str, EnrichedEmail] = {}
    for e in enriched:
        if predicate is not None and not predicate(e):
            continue
        current = chosen.get(e.match.email)
        if current is None or _tiebreak_rank(e) < _tiebreak_rank(current):
            chosen[e.match.email] = e

    joined = {
        email: " | ".join(urls.get(email) or ([rep.match.source_url] if rep.match.source_url else []))
        for email, rep in chosen.items()
    }
    return list(chosen.values()), joined


def build_frames(enriched: List[EnrichedEmail]) -> Dict[str, pd.DataFrame]:
    rows = [_row(e) for e in enriched]
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=list(_row.__annotations__) or ["email"])

    def sub(mask) -> pd.DataFrame:
        return df[mask].reset_index(drop=True) if not df.empty else df

    public = sub(df["match_type"] != "generated_candidate") if not df.empty else df

    accepted_items, accepted_urls = dedupe_by_email(
        enriched,
        lambda e: e.final_decision == "accept"
        and e.match.match_type != "generated_candidate",
    )
    accepted = pd.DataFrame(
        [
            {**_row(e), "source_urls_all": accepted_urls[e.match.email]}
            for e in accepted_items
        ]
    )

    review = sub(df["decision"] == "review") if not df.empty else df
    rejected = sub(df["decision"] == "reject") if not df.empty else df
    candidates = (
        sub(df["match_type"] == "generated_candidate") if not df.empty else df
    )

    frames = {
        "emails_publicos_encontrados.csv": public,
        "emails_aceptados_para_mailercheck.csv": accepted,
        "emails_review.csv": review,
        "emails_rechazados.csv": rejected,
        "emails_genericos_candidatos_no_confirmados.csv": candidates,
    }
    return frames


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
    items, urls = dedupe_by_email(
        enriched, lambda e: e.match.match_type != "generated_candidate"
    )
    rows = []
    for e in items:
        c = e.company
        cls = e.classification
        rows.append(
            {
                "EMAIL": e.match.email,
                "EMPRESA": c.company_name,
                "NOMBRE": "",
                "APELLIDO": "",
                "PROVINCIA": c.state_or_province,
                "CIUDAD": c.city,
                "TELEFONO": c.phone,
                "WEB": c.website,
                "FUENTE_URL": e.match.source_url,
                "source_urls_all": urls[e.match.email],
                "TIPO_EMAIL": cls.email_type if cls else "",
                "CONFIANZA": cls.confidence if cls else "",
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
    emails: list[str] = []
    for e in enriched:
        if e.match.match_type == "generated_candidate" and not include_candidates:
            continue
        if e.match.match_type != "generated_candidate" and e.final_decision == "reject":
            continue
        emails.append(e.match.email)
    return pd.DataFrame({"email": sorted(set(emails))})


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
