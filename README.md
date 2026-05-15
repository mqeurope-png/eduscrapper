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
8. Genera candidatos genéricos (`info@`, `contacto@`, ...) **solo** para
   empresas con dominio y sin email público aceptado, siempre marcados como
   `candidate_only` / `must_verify` / `brevo_recommended=false`.
9. Exporta CSVs y un directorio de auditoría.

## Salidas

CSVs descargables y guardados en `outputs/run_YYYYMMDD_HHMMSS/`:

- `emails_publicos_encontrados.csv`
- `emails_aceptados_para_mailercheck.csv`
- `emails_review.csv`
- `emails_rechazados.csv`
- `emails_genericos_candidatos_no_confirmados.csv`
- `targets_sin_email_encontrado.csv`
- `brevo_import_pre_verification.csv`
- `audit_log_urls_visitadas.csv`
- `run_config.json`, `visited_urls.csv`, `errors.csv`, `raw_email_matches.csv`

### MailerCheck

- **Generate MailerCheck file**: exporta una sola columna `email` con los
  aceptados (y candidatos si lo permites), deduplicados.
- **Importar resultados MailerCheck**: sube el CSV de MailerCheck y la app
  cruza por email y genera `emails_validos_finales.csv`,
  `emails_invalidos_descartados.csv` y `brevo_import_final.csv`.

Columnas del CSV final de Brevo: `EMAIL, EMPRESA, NOMBRE, APELLIDO, PROVINCIA,
CIUDAD, TELEFONO, WEB, FUENTE_URL, TIPO_EMAIL, CONFIANZA, FECHA_CAPTURA`.

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
