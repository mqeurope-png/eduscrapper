from __future__ import annotations

import io
import zipfile

import pandas as pd
import streamlit as st

from src.config import get_settings
from src.exporter import (
    MailerCheckFormatError,
    brevo_pre_verification,
    build_frames,
    cross_mailercheck,
    mailercheck_candidate_emails,
    mailercheck_file,
    mailercheck_public_emails,
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

CANDIDATE_MODE_LABELS = {
    "Ninguno": "none",
    "Conservador": "conservative",
    "Estándar": "standard",
    "Amplio": "broad",
}

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

    st.divider()
    cand_label = st.selectbox(
        "Modo de candidatos genéricos",
        list(CANDIDATE_MODE_LABELS.keys()),
        index=1,  # Conservador
        help=(
            "Ninguno: no genera. Conservador: info@, contacto@. "
            "Estándar: + comercial@. Amplio: hasta 6 prefijos."
        ),
    )
    candidate_mode = CANDIDATE_MODE_LABELS[cand_label]
    candidates_with_review = st.checkbox(
        "Generar candidatos aunque existan emails en review",
        value=False,
    )

    st.divider()
    auto_resolve = st.checkbox(
        "Resolver dominios desconocidos con OpenAI Web Search",
        value=False,
        disabled=not settings.openai_enabled,
        help=(
            "Para filas sin dominio: usa la búsqueda web de OpenAI para "
            "encontrar la web oficial. Requiere OPENAI_API_KEY. Coste por "
            "consulta según tarifa de OpenAI."
        ),
    )

    if st.session_state.get("last_run_dir"):
        st.success(
            f"Últimos resultados guardados en: "
            f"`{st.session_state['last_run_dir']}`"
        )
        if st.button("Limpiar resultados actuales", width="content"):
            for k in (
                "enriched",
                "scrapes",
                "companies",
                "resolutions",
                "last_run_dir",
            ):
                st.session_state.pop(k, None)
            st.rerun()

st.info(
    "Uso responsable: solo fuentes públicas y contacto B2B legítimo. "
    "Los candidatos genéricos NO son emails encontrados públicamente: son "
    "hipótesis por patrón y deben verificarse con MailerCheck antes de "
    "cualquier uso. Incluya opt-out en las campañas."
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
    frames["mailercheck_public_emails.csv"] = mailercheck_public_emails(enriched)
    frames["mailercheck_candidate_emails.csv"] = mailercheck_candidate_emails(
        enriched
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
            f"a procesar tras filtros: **{len(companies)}** — "
            f"modo candidatos: **{cand_label}**"
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
            _rp = None
            if auto_resolve and settings.openai_enabled:
                rbar = st.progress(0.0, text="Resolviendo dominios...")

                def _rp(done: int, total: int) -> None:
                    rbar.progress(
                        done / max(total, 1),
                        text=f"Resolviendo dominios {done}/{total}",
                    )

            pbar = st.progress(0.0, text="Scraping...")

            def _sp(done: int, total: int) -> None:
                pbar.progress(done / max(total, 1), text=f"Scraping {done}/{total}")

            cbar = st.progress(0.0, text="Procesando...")

            def _cp(done: int, total: int) -> None:
                cbar.progress(
                    done / max(total, 1), text=f"Clasificando {done}/{total}"
                )

            enriched, scrapes, resolutions = run_pipeline(
                companies,
                use_ai=use_ai,
                candidate_mode=candidate_mode,
                candidates_with_review=candidates_with_review,
                auto_resolve_domains=auto_resolve,
                scrape_progress=_sp,
                classify_progress=_cp,
                resolve_progress=_rp,
            )

            run_config = {
                "use_ai": use_ai,
                "rows_input": len(companies_all),
                "rows_processed": len(companies),
                "only_with_domain": only_domain,
                "only_high_priority": only_high,
                "max_pages_per_domain": int(max_pages),
                "openai_enabled": settings.openai_enabled,
                "candidate_mode": candidate_mode,
                "candidates_with_review": candidates_with_review,
                "auto_resolve_domains": auto_resolve,
            }
            run_dir = write_run(
                enriched, companies, scrapes, run_config, resolutions=resolutions
            )

            st.session_state["enriched"] = enriched
            st.session_state["scrapes"] = scrapes
            st.session_state["companies"] = companies
            st.session_state["resolutions"] = resolutions
            st.session_state["last_run_dir"] = str(run_dir)
            st.rerun()

    if "enriched" in st.session_state:
        enriched = st.session_state["enriched"]
        scrapes = st.session_state["scrapes"]
        companies = st.session_state["companies"]

        st.success(
            f"Resultados guardados en `{st.session_state['last_run_dir']}` "
            "(CSVs limpios y deduplicados por email)."
        )

        frames = _operational_frames(enriched, companies, scrapes, False)
        n_cand = len(frames["emails_genericos_candidatos_no_confirmados.csv"])

        resolutions = st.session_state.get("resolutions") or []
        if resolutions:
            st.header("Resolución de dominios")
            r_done = sum(1 for r in resolutions if r.chosen_domain)
            r_low = sum(1 for r in resolutions if r.chosen_domain and r.confidence == "low")
            r_err = sum(1 for r in resolutions if r.error)
            rc = st.columns(4)
            rc[0].metric("Intentadas", len(resolutions))
            rc[1].metric("Resueltas", r_done)
            rc[2].metric("Baja confianza", r_low)
            rc[3].metric("Errores", r_err)
            from src.exporter import resolutions_frame
            res_df = resolutions_frame(resolutions)
            st.dataframe(res_df, height=200, width="stretch")
            st.download_button(
                "Descargar domain_resolutions.csv",
                res_df.to_csv(index=False, encoding="utf-8-sig"),
                file_name="domain_resolutions.csv",
                mime="text/csv",
            )

        st.header("Emails públicos")
        m = st.columns(5)
        m[0].metric("Empresas", len(companies))
        m[1].metric(
            "Encontrados", len(frames["emails_publicos_encontrados.csv"])
        )
        m[2].metric(
            "Aceptados", len(frames["emails_aceptados_para_mailercheck.csv"])
        )
        m[3].metric("Review", len(frames["emails_review.csv"]))
        m[4].metric("Rechazados", len(frames["emails_rechazados.csv"]))

        st.dataframe(
            frames["emails_aceptados_para_mailercheck.csv"],
            height=320,
            width="stretch",
        )
        st.download_button(
            "Exportar emails públicos aceptados para MailerCheck "
            f"({len(frames['mailercheck_public_emails.csv'])})",
            frames["mailercheck_public_emails.csv"].to_csv(index=False),
            file_name="mailercheck_public_emails.csv",
            mime="text/csv",
        )

        st.header("Candidatos genéricos")
        st.write(
            f"Modo usado: **{cand_label}** — candidatos generados: "
            f"**{n_cand}** (separados de los emails públicos)."
        )
        st.warning(
            "Estos emails NO fueron encontrados públicamente. Son hipótesis "
            "por patrón y deben verificarse antes de cualquier uso."
        )
        st.dataframe(
            frames["emails_genericos_candidatos_no_confirmados.csv"],
            height=240,
            width="stretch",
        )
        st.download_button(
            "Exportar candidatos genéricos para MailerCheck "
            f"({len(frames['mailercheck_candidate_emails.csv'])})",
            frames["mailercheck_candidate_emails.csv"].to_csv(index=False),
            file_name="mailercheck_candidate_emails.csv",
            mime="text/csv",
        )

        st.header("Descargas")
        inc = st.checkbox(
            "Incluir candidatos genéricos no confirmados en "
            "mailercheck_emails.csv",
            value=False,
            key="inc_candidates",
        )
        frames["mailercheck_emails.csv"] = mailercheck_file(enriched, inc)

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
        "públicos y los candidatos genéricos de esta sesión."
    )
    st.warning(
        "Los candidatos genéricos verificados técnicamente NO fueron "
        "encontrados públicamente. Úsalos en campaña separada o con etiqueta "
        "específica en Brevo."
    )
    if "enriched" not in st.session_state:
        st.info("Primero ejecuta el enriquecimiento en la pestaña anterior.")
    else:
        include_combined = st.checkbox(
            "Incluir candidatos genéricos verificados en el CSV final "
            "combinado",
            value=False,
        )
        mc_up = st.file_uploader(
            "CSV de MailerCheck", type=["csv"], key="mc_upload"
        )
        if mc_up is not None:
            mc_df = read_csv_bytes(mc_up.getvalue())
            st.dataframe(mc_df.head(10), width="stretch")
            try:
                result = cross_mailercheck(
                    st.session_state["enriched"], mc_df, include_combined
                )
            except MailerCheckFormatError as exc:
                st.error(f"No se pudo procesar el CSV de MailerCheck: {exc}")
                result = None

            if result is not None:
                cp = st.columns(3)
                cp[0].metric(
                    "Públicos válidos",
                    len(result["emails_publicos_validos_finales.csv"]),
                )
                cp[1].metric(
                    "Públicos descartados",
                    len(result["emails_publicos_invalidos_descartados.csv"]),
                )
                cp[2].metric(
                    "Públicos risky",
                    len(result["emails_publicos_risky_review.csv"]),
                )
                cc = st.columns(3)
                cc[0].metric(
                    "Candidatos válidos",
                    len(result["candidatos_genericos_validos.csv"]),
                )
                cc[1].metric(
                    "Candidatos descartados",
                    len(result["candidatos_genericos_invalidos.csv"]),
                )
                cc[2].metric(
                    "Candidatos risky",
                    len(result["candidatos_genericos_risky_review.csv"]),
                )

                for name, frame in result.items():
                    if name == "brevo_import_final_combined.csv" and not (
                        include_combined
                    ):
                        continue
                    st.download_button(
                        f"Descargar {name} ({len(frame)} filas)",
                        frame.to_csv(index=False, encoding="utf-8-sig"),
                        file_name=name,
                        mime="text/csv",
                        key=f"mc_dl_{name}",
                    )
