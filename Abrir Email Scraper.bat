@echo off
chcp 65001 >nul
title Email Scraper
setlocal enabledelayedexpansion

REM Ir a la carpeta de la app (donde esta este .bat)
cd /d "%~dp0"

echo ==========================================================
echo   EMAIL SCRAPER - Iniciando
echo   Carpeta: %CD%
echo ==========================================================
echo.

REM --- 1. Localizar Python 3.11 ---
set "PYEXE="
where py >nul 2>nul
if !errorlevel! == 0 (
    py -3.11 --version >nul 2>nul
    if !errorlevel! == 0 set "PYEXE=py -3.11"
)
if "!PYEXE!" == "" (
    where python >nul 2>nul
    if !errorlevel! == 0 set "PYEXE=python"
)
if "!PYEXE!" == "" (
    echo [ERROR] No se encontro Python.
    echo Instala Python 3.11 desde https://www.python.org/downloads/release/python-3119/
    echo Marca la casilla "Add python.exe to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)
echo [OK] Python detectado: !PYEXE!

REM --- 2. Crear .venv si no existe ---
if not exist ".venv\Scripts\activate.bat" (
    echo [..] Creando entorno virtual .venv (solo la primera vez)...
    !PYEXE! -m venv .venv
    if !errorlevel! neq 0 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
    echo [OK] Entorno virtual creado.
) else (
    echo [OK] Entorno virtual .venv ya existe.
)

REM --- 3. Activar entorno virtual ---
call ".venv\Scripts\activate.bat"
if !errorlevel! neq 0 (
    echo [ERROR] No se pudo activar el entorno virtual.
    pause
    exit /b 1
)

REM --- 4. Instalar dependencias solo si hace falta ---
set "MARKER=.venv\.requirements_installed"
set "NEED_INSTALL=0"
if not exist "!MARKER!" set "NEED_INSTALL=1"
if exist "!MARKER!" (
    REM Reinstala si requirements.txt es mas nuevo que el marcador
    for /f %%i in ('dir /b /o-d "requirements.txt" "!MARKER!" 2^>nul') do (
        if "%%i" == "requirements.txt" set "NEED_INSTALL=1"
        goto :after_check
    )
)
:after_check
if "!NEED_INSTALL!" == "1" (
    echo [..] Instalando dependencias (puede tardar 1-3 minutos)...
    python -m pip install --upgrade pip >nul
    python -m pip install -r requirements.txt
    if !errorlevel! neq 0 (
        echo [ERROR] Fallo la instalacion de dependencias.
        pause
        exit /b 1
    )
    echo instalado > "!MARKER!"
    echo [OK] Dependencias instaladas.
) else (
    echo [OK] Dependencias ya instaladas.
)

REM --- 5. Crear .env si no existe ---
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo.
        echo [AVISO] Se creo el archivo .env a partir de .env.example.
        echo         Si quieres usar la clasificacion con IA, abre .env
        echo         con el Bloc de notas y pon tu clave en OPENAI_API_KEY=
        echo         Sin clave, la app funciona en modo "solo scraping".
        echo.
    )
) else (
    echo [OK] Archivo .env encontrado.
)

REM --- 6. Lanzar Streamlit y abrir el navegador ---
echo.
echo ==========================================================
echo   La app se abrira en: http://localhost:8501
echo   Para PARAR la app: cierra esta ventana o pulsa Ctrl+C.
echo ==========================================================
echo.

REM Abrir el navegador tras unos segundos por si Streamlit no lo hace
start "" cmd /c "timeout /t 6 >nul & start http://localhost:8501"

python -m streamlit run app.py

echo.
echo La app se ha detenido. Revisa los mensajes de arriba si hubo errores.
pause
