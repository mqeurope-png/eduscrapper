# Instalar y usar en Windows (10 / 11)

Guía sin comandos: solo doble clic. No usa `.exe` ni instaladores raros.

Carpeta recomendada de la app (puede ser cualquiera, pero como ejemplo):

```
C:\Users\whats\OneDrive\Documents\BOMEDIA\APP Scrapper\scrapperv2
```

Descomprime el ZIP ahí y deja todos los archivos juntos (los `.bat` deben
quedar en la misma carpeta que `app.py`).

---

## 1. Instalar Python 3.11 (solo la primera vez)

1. Entra en: https://www.python.org/downloads/release/python-3119/
2. Baja hasta **"Windows installer (64-bit)"** y descárgalo.
3. Ejecuta el instalador y **marca la casilla "Add python.exe to PATH"**
   (abajo del todo) antes de pulsar **Install Now**.
4. Termina la instalación.

Si ya tienes Python 3.11 instalado, sáltate este paso.

---

## 2. Abrir la app

**Haz doble clic en `INICIAR_EMAIL_SCRAPER.bat`**

Es el único launcher. La primera vez tarda 1-3 minutos: crea el entorno
`.venv`, instala las dependencias y prepara el archivo `.env`. Verás
mensajes en español en una ventana negra. Cuando esté listo, el navegador
se abre solo en:

```
http://localhost:8501
```

Cada vez comprueba e instala dependencias (tarda un poco más, pero es
fiable). No necesitas editar ningún `.bat` nunca.

> **No cierres la ventana negra mientras uses la app. Para cerrar la app,
> pulsa `Ctrl + C` o cierra la ventana.**

¿Quieres un icono en el Escritorio? Clic derecho en
`crear_acceso_directo_windows.ps1` → **Ejecutar con PowerShell**. Creará un
acceso directo llamado **"Email Scraper"**.

---

## 3. Cómo parar la app

- Cierra la ventana negra del `.bat`, **o**
- Haz clic en esa ventana y pulsa `Ctrl + C`.

Cerrar solo la pestaña del navegador NO para la app; hay que cerrar la
ventana negra.

---

## 4. Editar `.env` (clave de OpenAI, opcional)

Solo si quieres la clasificación con IA:

1. **Doble clic en `CONFIGURAR_OPENAI.bat`** (crea `.env` si no existe y lo
   abre en el Bloc de notas automáticamente).
2. En la línea `OPENAI_API_KEY=` escribe tu clave después del `=`:
   ```
   OPENAI_API_KEY=sk-tu-clave-aqui
   ```
3. Guarda (`Ctrl + S`) y cierra el Bloc de notas.
4. Si la app estaba abierta, ciérrala y vuelve a abrirla.

Sin clave, la app funciona igual en modo **"solo scraping"**.

---

## 5. Si Windows bloquea el `.bat`

Windows SmartScreen puede avisar al abrir un `.bat` descargado:

- Si sale **"Windows protegió tu PC"**: pulsa **"Más información"** →
  **"Ejecutar de todas formas"**.
- Si el archivo aparece **bloqueado**: clic derecho sobre el `.bat` →
  **Propiedades** → marca **"Desbloquear"** abajo → **Aceptar**.
- Para el `.ps1`, si PowerShell se queja de permisos, ábrelo así: clic
  derecho en la carpeta con `Shift` → "Abrir ventana de PowerShell aquí" →
  pega:
  ```
  powershell -ExecutionPolicy Bypass -File ".\crear_acceso_directo_windows.ps1"
  ```

Estos archivos solo crean un entorno local y lanzan la app; no instalan
nada en el sistema fuera de la carpeta.

---

## 6. Si falta Python / da error de Python

- Mensaje **"No se encontro Python"**: instala Python 3.11 (paso 1) y
  **asegúrate de marcar "Add python.exe to PATH"**. Reinicia el `.bat`.
- Si tienes varias versiones, el launcher intenta usar `py -3.11`. Si no
  existe esa versión exacta, usa cualquier `python` del PATH; idealmente
  instala la 3.11.
- Mensaje al crear `.venv`: cierra OneDrive un momento o mueve la carpeta
  fuera de OneDrive si la sincronización bloquea archivos.

---

## 7. Si no se abre el navegador

- Espera ~10 segundos: el launcher abre el navegador con un pequeño retraso.
- Si aun así no abre, escribe a mano en Chrome/Edge:
  ```
  http://localhost:8501
  ```
- Si dice que el puerto está ocupado, cierra otras ventanas negras de la
  app y vuelve a abrir el `.bat`.

---

## Modos de candidatos y flujo recomendado

- **Email público** = encontrado en la web (fiable, lista principal).
- **Candidato genérico** = inventado por patrón (`info@`, `contacto@`...).
  NO se encontró en ninguna parte: **no lo uses sin verificar antes con
  MailerCheck**. Siempre va en archivos separados.

En la barra lateral, "Modo de candidatos genéricos":

- **Ninguno**: no genera.
- **Conservador** (por defecto): solo `info@` y `contacto@`. Recomendado:
  menos ruido y menos coste en MailerCheck.
- **Estándar**: añade `comercial@`.
- **Amplio**: hasta 6 prefijos.

Flujo recomendado:

1. Scraping + IA.
2. Botón "Exportar emails públicos aceptados para MailerCheck".
3. En tanda aparte: "Exportar candidatos genéricos para MailerCheck".
4. Verifica ambos en MailerCheck.
5. Pestaña "2. Importar resultados MailerCheck": sube el CSV de MailerCheck.
6. Usa `brevo_import_public_validated.csv` como lista principal y
   `brevo_import_candidates_verified.csv` como lista **separada**.

Entregabilidad: empieza con lotes pequeños, opt-out claro, no reimportes
bloqueados/baja/hard bounce, y no metas emails `invalid`/`risky` en Brevo.

## Nota para usuarios técnicos

Los `.bat` no cambian la forma normal de ejecutar la app. Sigue siendo
válido, dentro de la carpeta y con el entorno activado:

```
streamlit run app.py
```
