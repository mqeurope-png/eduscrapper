from __future__ import annotations

import io
from typing import Dict, List

import pandas as pd

from .models import Company
from .normalize import (
    dedupe_key,
    normalize_company,
    normalize_domain,
    normalize_phone,
    normalize_province,
    normalize_website,
)

CANONICAL_COLUMNS = [
    "company_name",
    "website",
    "domain",
    "country",
    "state_or_province",
    "city",
    "address",
    "phone",
    "industry_hint",
    "enrichment_priority",
    "search_query",
    "source",
    "source_rows",
]

_ENCODINGS = ["utf-8-sig", "utf-8", "latin1"]


def read_csv_bytes(data: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for enc in _ENCODINGS:
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc, dtype=str).fillna("")
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_error = exc
    raise ValueError(f"Could not parse CSV with known encodings: {last_error}")


def guess_mapping(columns: List[str]) -> Dict[str, str]:
    lower = {c.lower().strip(): c for c in columns}
    mapping: Dict[str, str] = {}
    for canon in CANONICAL_COLUMNS:
        if canon in lower:
            mapping[canon] = lower[canon]
    return mapping


def apply_mapping(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    out = pd.DataFrame()
    for canon in CANONICAL_COLUMNS:
        src = mapping.get(canon)
        out[canon] = df[src].astype(str) if src and src in df.columns else ""
    return out


def to_companies(df: pd.DataFrame, dedupe: bool = True) -> List[Company]:
    seen = set()
    companies: List[Company] = []
    for _, row in df.iterrows():
        website = normalize_website(row.get("website", ""), row.get("domain", ""))
        domain = normalize_domain(row.get("domain", ""), website)
        if not website and domain:
            website = normalize_website("", domain)
        company = Company(
            company_name=normalize_company(row.get("company_name", "")),
            website=website,
            domain=domain,
            country=str(row.get("country", "")).strip(),
            state_or_province=normalize_province(row.get("state_or_province", "")),
            city=str(row.get("city", "")).strip(),
            address=str(row.get("address", "")).strip(),
            phone=normalize_phone(row.get("phone", "")),
            industry_hint=str(row.get("industry_hint", "")).strip(),
            enrichment_priority=str(row.get("enrichment_priority", "")).strip(),
            search_query=str(row.get("search_query", "")).strip(),
            source=str(row.get("source", "")).strip(),
            source_rows=str(row.get("source_rows", "")).strip(),
        )
        if not company.company_name and not company.domain:
            continue
        if dedupe:
            key = dedupe_key(company.company_name, company.domain)
            if key in seen:
                continue
            seen.add(key)
        companies.append(company)
    return companies


def filter_companies(
    companies: List[Company],
    only_with_domain: bool = False,
    only_high_priority: bool = False,
    max_rows: int | None = None,
) -> List[Company]:
    out = list(companies)
    if only_with_domain:
        out = [c for c in out if c.domain]
    if only_high_priority:
        out = [
            c
            for c in out
            if c.enrichment_priority.strip().lower() in {"alta", "high", "alto"}
        ]
    if max_rows and max_rows > 0:
        out = out[:max_rows]
    return out
