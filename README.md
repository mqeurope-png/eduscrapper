# B2B Email Enrichment

Mini app local para enriquecer emails B2B a partir de un CSV de empresas.
Lee un CSV, busca emails públicos en las webs oficiales, los puntúa de forma
determinista, opcionalmente los clasifica con OpenAI, genera candidatos
genéricos cuando no hay email público, y exporta CSVs limpios para
verificación (MailerCheck) e importación (Brevo).

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env   # rellena OPENAI_API_KEY si quieres clasificación IA
streamlit run app.py
```

La app es 100% local. No usa base de datos ni despliegue cloud.

## Variables de entorno (`.env`)

| Variable | Descripción |
| --- | --- |
| `OPENAI_API_KEY` | Clave OpenAI. Si está vacía, la app funciona en modo *scraping only* y marca los emails como `needs_ai_classification`. |
| `OPENAI_MODEL_FAST` | Modelo rápido para casos sencillos. |
| `OPENAI_MODEL_STRONG` | Modelo fuerte para casos dudosos. |
| `REQUEST_TIMEOUT` | Timeout HTTP en segundos. |
| `MAX_PAGES_PER_DOMAIN` | Máximo de páginas por dominio. |
| `MAX_CONCURRENT_REQUESTS` | Concurrencia de scraping. |

## Flujo

1. Sube el CSV de empresas y mapea columnas si usan otros nombres.
2. Filtra: todas / solo con dominio / solo prioridad Alta / primeras N.
3. La app normaliza empresa, web, dominio, teléfono y provincia, y deduplica.
4. Visita páginas públicas probables (`/`, `/contacto`, `/aviso-legal`,
   `/privacidad`, `/quienes-somos`, ...) respetando timeout y límite de páginas.
5. Extrae emails (normales, ofuscados, `mailto:`) y filtra basura.
6. Puntuación determinista previa a la IA.
7. Clasificación opcional con OpenAI (JSON estricto validado con Pydantic;
   un reintento de corrección; si falla, `review`). El modelo **no** busca en
   internet: solo usa el contenido ya scrapeado.
8. Genera candidatos genéricos según el **modo de candidatos** elegido,
   **solo** para empresas con dominio corporativo válido y sin email público
   aceptado, siempre marcados como `must_verify` / `brevo_recommended=false`.
9. Exporta CSVs y un directorio de auditoría.

## Email público encontrado vs. candidato generado

- **Email público encontrado**: aparece publicado en la web de la empresa
  (contacto, aviso legal, etc.). Tiene `source_url`. Es la lista principal.
- **Candidato genérico**: NO fue encontrado en ninguna parte. Es una
  hipótesis por patrón (`info@dominio`, `contacto@dominio`...). No tiene
  `source_url`. **Nunca** debe usarse sin verificar antes con MailerCheck.

Ambos se mantienen **siempre separados** en archivos distintos.

## Modos de candidatos genéricos

Selector en la barra lateral. Solo se generan para empresas con dominio
corporativo y sin email público aceptado (los dominios gratuitos, redes
sociales, directorios, marketplaces y hosting se excluyen).

| Modo | Prefijos generados |
| --- | --- |
| Ninguno | (no genera) |
| **Conservador** (por defecto) | `info@`, `contacto@` |
| Estándar | `info@`, `contacto@`, `comercial@` |
| Amplio | `info@`, `contacto@`, `comercial@`, `ventas@`, `hola@`, `administracion@` |

Por defecto **no** se generan candidatos si la empresa solo tiene emails en
review, salvo que actives "Generar candidatos aunque existan emails en
review". Conservador reduce drásticamente el ruido (y el coste de
MailerCheck) frente a Amplio.

## Salidas

CSVs descargables y guardados en `outputs/run_YYYYMMDD_HHMMSS/`:

- `raw_email_matches.csv` (todos los matches, sin deduplicar)
- `emails_publicos_encontrados.csv`
- `emails_aceptados_para_mailercheck.csv`
- `emails_review.csv`
- `emails_rechazados.csv`
- `emails_genericos_candidatos_no_confirmados.csv`
- `targets_sin_email_encontrado.csv`
- `brevo_import_pre_verification.csv`
- `mailercheck_emails.csv` (por defecto solo públicos aceptados)
- `mailercheck_public_emails.csv` (solo públicos aceptados)
- `mailercheck_candidate_emails.csv` (solo candidatos genéricos)
- `audit_log_urls_visitadas.csv`, `visited_urls.csv`, `errors.csv`
- `run_config.json`

Tras importar el CSV de MailerCheck se generan, separados:

- `emails_publicos_validos_finales.csv`
- `emails_publicos_invalidos_descartados.csv`
- `emails_publicos_risky_review.csv`
- `candidatos_genericos_validos.csv`
- `candidatos_genericos_invalidos.csv`
- `candidatos_genericos_risky_review.csv`
- `brevo_import_public_validated.csv`
- `brevo_import_candidates_verified.csv`
- `brevo_import_final_combined.csv` (solo si activas la opción de combinar)

### Flujo recomendado

1. Scraping + IA.
2. Exportar **públicos aceptados** a MailerCheck
   (`mailercheck_public_emails.csv`).
3. Exportar **candidatos** a MailerCheck en una **tanda separada**
   (`mailercheck_candidate_emails.csv`).
4. Importar los resultados de MailerCheck en la pestaña 2.
5. Usar `brevo_import_public_validated.csv` como **lista principal**.
6. Usar `brevo_import_candidates_verified.csv` como **lista separada**, o
   solo si activas el CSV combinado (públicos y candidatos no se mezclan
   por defecto; si se combinan, la columna `FUENTE_EMAIL` los distingue y
   gana el público).

Columnas del CSV final de Brevo: `EMAIL, EMPRESA, NOMBRE, APELLIDO,
PROVINCIA, CIUDAD, TELEFONO, WEB, FUENTE_URL, FUENTE_URLS_ALL, TIPO_EMAIL,
CONFIANZA, FUENTE_EMAIL, FECHA_CAPTURA, VERIFICATION_STATUS,
VERIFICATION_PROVIDER`. `FUENTE_EMAIL` = `publico_web_validado` o
`candidato_generico_verificado`.

### Entregabilidad y Brevo

- Empieza con **lotes pequeños** y calienta el dominio.
- Opt-out claro en cada campaña.
- No mezcles bases problemáticas ni reimportes bloqueados / baja / hard
  bounce.
- No metas emails `invalid` ni `risky` en la lista final de Brevo.

## Privacidad y cumplimiento

- Usa esta herramienta **solo** para fuentes públicas y contacto B2B legítimo.
- Los emails candidatos **no** deben importarse en Brevo sin verificación previa.
- Verifica con MailerCheck antes de cualquier campaña.
- Incluye un opt-out claro en todas las campañas.
- No reimportes emails bloqueados, dados de baja o con hard bounce previo.
- El scraper respeta timeouts, hace pausas, limita concurrencia, no entra en
  páginas de login, no salta captchas, no usa LinkedIn cerrado ni paywalls, y
  guarda siempre la URL fuente de cada email.

## Tests

```bash
pip install pytest
pytest -q
```
