from __future__ import annotations

import io
import zipfile

import pandas as pd
import streamlit as st

from src.config import get_settings
from src.exporter import (
    brevo_pre_verification,
    build_frames,
    cross_mailercheck,
    mailercheck_file,
    targets_without_email,
    write_run,
)
from src.io_utils import (
    CANONICAL_COLUMNS,
    apply_mapping,
    filter_companies,
    guess_mapping,
    read_csv_bytes,
    to_companies,
)
from src.pipeline import run_pipeline

st.set_page_config(page_title="B2B Email Enrichment", layout="wide")
st.title("B2B Email Enrichment")

settings = get_settings()

with st.sidebar:
    st.header("Configuración")
    st.write(
        "OpenAI:",
        "✅ habilitado" if settings.openai_enabled else "⚠️ scraping only",
    )
    max_rows = st.number_input("Número máximo de filas (0 = todas)", 0, 100000, 0)
    max_pages = st.number_input(
        "Máximo páginas por dominio", 1, 30, settings.max_pages_per_domain
    )
    only_domain = st.checkbox("Solo filas con dominio", value=True)
    only_high = st.checkbox("Solo prioridad Alta", value=False)
    dedupe = st.checkbox("Deduplicar por dominio + empresa", value=True)
    settings.max_pages_per_domain = int(max_pages)
    if st.session_state.get("last_run_dir"):
        st.success(
            f"Últimos resultados guardados en: "
            f"`{st.session_state['last_run_dir']}`"
        )
        if st.button("Limpiar resultados actuales", width="content"):
            for k in ("enriched", "scrapes", "companies", "last_run_dir"):
                st.session_state.pop(k, None)
            st.rerun()

st.info(
    "Uso responsable: solo fuentes públicas y contacto B2B legítimo. "
    "Los candidatos generados NO deben importarse a Brevo sin verificación "
    "previa (MailerCheck). Incluya opt-out en las campañas."
)

tab_enrich, tab_mailercheck = st.tabs(
    ["1. Enriquecer", "2. Importar resultados MailerCheck"]
)


def _zip_frames(frames: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, frame in frames.items():
            zf.writestr(name, frame.to_csv(index=False, encoding="utf-8-sig"))
    return buf.getvalue()


def _operational_frames(enriched, companies, scrapes, include_candidates):
    """Exactly the clean, deduplicated CSVs the user sees and downloads."""
    frames = build_frames(enriched)
    frames["targets_sin_email_encontrado.csv"] = targets_without_email(
        enriched, companies, scrapes
    )
    frames["brevo_import_pre_verification.csv"] = brevo_pre_verification(enriched)
    frames["mailercheck_emails.csv"] = mailercheck_file(
        enriched, include_candidates
    )
    return frames


with tab_enrich:
    uploaded = st.file_uploader("Sube el CSV de empresas", type=["csv"])
    if uploaded is not None:
        raw = read_csv_bytes(uploaded.getvalue())
        st.subheader("Preview")
        st.dataframe(raw.head(20), width="stretch")

        st.subheader("Mapeo de columnas")
        guessed = guess_mapping(list(raw.columns))
        options = ["(ninguna)"] + list(raw.columns)
        mapping: dict[str, str] = {}
        cols = st.columns(3)
        for i, canon in enumerate(CANONICAL_COLUMNS):
            with cols[i % 3]:
                default = guessed.get(canon, "(ninguna)")
                sel = st.selectbox(
                    canon,
                    options,
                    index=options.index(default) if default in options else 0,
                    key=f"map_{canon}",
                )
                if sel != "(ninguna)":
                    mapping[canon] = sel

        mapped = apply_mapping(raw, mapping)
        companies_all = to_companies(mapped, dedupe=dedupe)
        companies = filter_companies(
            companies_all,
            only_with_domain=only_domain,
            only_high_priority=only_high,
            max_rows=int(max_rows) or None,
        )
        st.write(
            f"Filas normalizadas: **{len(companies_all)}** — "
            f"a procesar tras filtros: **{len(companies)}**"
        )

        c1, c2 = st.columns(2)
        run_scrape = c1.button("Run scraping only", width="stretch")
        run_ai = c2.button(
            "Run scraping + AI classification",
            width="stretch",
            disabled=not settings.openai_enabled,
        )

        if run_scrape or run_ai:
            use_ai = bool(run_ai)
            pbar = st.progress(0.0, text="Scraping...")

            def _sp(done: int, total: int) -> None:
                pbar.progress(done / max(total, 1), text=f"Scraping {done}/{total}")

            cbar = st.progress(0.0, text="Procesando...")

            def _cp(done: int, total: int) -> None:
                cbar.progress(
                    done / max(total, 1), text=f"Clasificando {done}/{total}"
                )

            enriched, scrapes = run_pipeline(
                companies, use_ai=use_ai, scrape_progress=_sp, classify_progress=_cp
            )

            run_config = {
                "use_ai": use_ai,
                "rows_input": len(companies_all),
                "rows_processed": len(companies),
                "only_with_domain": only_domain,
                "only_high_priority": only_high,
                "max_pages_per_domain": int(max_pages),
                "openai_enabled": settings.openai_enabled,
            }
            run_dir = write_run(enriched, companies, scrapes, run_config)

            st.session_state["enriched"] = enriched
            st.session_state["scrapes"] = scrapes
            st.session_state["companies"] = companies
            st.session_state["last_run_dir"] = str(run_dir)
            st.rerun()

    # Results render from session_state so downloads never clear them.
    if "enriched" in st.session_state:
        enriched = st.session_state["enriched"]
        scrapes = st.session_state["scrapes"]
        companies = st.session_state["companies"]

        st.success(
            f"Resultados guardados en `{st.session_state['last_run_dir']}` "
            "(CSVs limpios y deduplicados por email)."
        )

        decisions = [e.final_decision for e in enriched]
        generated = sum(
            1 for e in enriched if e.match.match_type == "generated_candidate"
        )
        m = st.columns(7)
        m[0].metric("Empresas", len(companies))
        m[1].metric("Dominios visitados", len({s.company.domain for s in scrapes}))
        m[2].metric("Emails (raw)", len(enriched) - generated)
        m[3].metric("Aceptados", decisions.count("accept"))
        m[4].metric("Review", decisions.count("review"))
        m[5].metric("Rechazados", decisions.count("reject"))
        m[6].metric("Candidatos", generated)

        st.subheader("Generate MailerCheck file")
        inc = st.checkbox(
            "Incluir candidatos genéricos no confirmados",
            value=False,
            key="inc_candidates",
        )

        frames = _operational_frames(enriched, companies, scrapes, inc)

        st.subheader("Resultados (deduplicados por email)")
        st.dataframe(
            frames["emails_aceptados_para_mailercheck.csv"],
            height=380,
            width="stretch",
        )

        for name, frame in frames.items():
            st.download_button(
                f"Descargar {name} ({len(frame)} filas)",
                frame.to_csv(index=False, encoding="utf-8-sig"),
                file_name=name,
                mime="text/csv",
                key=f"dl_{name}",
            )

        st.download_button(
            "Descargar TODO (zip) — exactamente estos CSVs limpios",
            _zip_frames(frames),
            file_name="resultados.zip",
            mime="application/zip",
        )


with tab_mailercheck:
    st.write(
        "Sube el CSV exportado por MailerCheck para cruzarlo con los emails "
        "encontrados en esta sesión."
    )
    if "enriched" not in st.session_state:
        st.warning("Primero ejecuta el enriquecimiento en la pestaña anterior.")
    else:
        mc_up = st.file_uploader(
            "CSV de MailerCheck", type=["csv"], key="mc_upload"
        )
        if mc_up is not None:
            mc_df = read_csv_bytes(mc_up.getvalue())
            st.dataframe(mc_df.head(10), width="stretch")
            result = cross_mailercheck(st.session_state["enriched"], mc_df)
            for name, frame in result.items():
                st.write(f"**{name}** — {len(frame)} filas")
                st.download_button(
                    f"Descargar {name}",
                    frame.to_csv(index=False, encoding="utf-8-sig"),
                    file_name=name,
                    mime="text/csv",
                    key=f"mc_dl_{name}",
                )
