@echo off
setlocal
title Email Scraper

echo ==========================================================
echo   EMAIL SCRAPER - Iniciando
echo ==========================================================

cd /d "%~dp0"

echo Carpeta actual:
echo %CD%
echo.

if not exist "app.py" (
    echo [ERROR] No encuentro app.py en esta carpeta.
    echo Asegurate de ejecutar este archivo desde la carpeta de la app.
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [ERROR] No encuentro requirements.txt en esta carpeta.
    pause
    exit /b 1
)

echo [1/5] Comprobando Python 3.11...

py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No encuentro Python 3.11.
    echo Instala Python 3.11 desde python.org y marca Add python.exe to PATH.
    pause
    exit /b 1
)

echo [OK] Python 3.11 detectado.
echo.

echo [2/5] Comprobando entorno virtual...

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual .venv...
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
) else (
    echo [OK] Entorno virtual existente.
)

echo.

echo [3/5] Activando entorno virtual...
call ".venv\Scripts\activate.bat"

if errorlevel 1 (
    echo [ERROR] No se pudo activar el entorno virtual.
    pause
    exit /b 1
)

echo.

echo [4/5] Instalando dependencias...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo [ERROR] Fallo instalando dependencias.
    pause
    exit /b 1
)

echo.

echo [5/5] Comprobando archivo .env...

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [AVISO] Se ha creado .env desde .env.example.
        echo Si quieres usar IA, ejecuta CONFIGURAR_OPENAI.bat y pega tu OPENAI_API_KEY.
    ) else (
        echo [AVISO] No existe .env.example. La app funcionara sin IA si no hay OPENAI_API_KEY.
    )
) else (
    echo [OK] Archivo .env encontrado. No se sobrescribe.
)

echo.
echo No cierres esta ventana negra mientras uses la app.
echo Para cerrar la app, pulsa Ctrl+C o cierra la ventana.
echo.
echo Abriendo navegador en http://localhost:8501 ...
start "" "http://localhost:8501"

echo.
echo Lanzando Email Scraper...
python -m streamlit run app.py

echo.
echo La app se ha cerrado.
pause
