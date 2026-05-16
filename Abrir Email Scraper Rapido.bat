@echo off
chcp 65001 >nul
title Email Scraper (rapido)
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ==========================================================
echo   EMAIL SCRAPER - Inicio rapido
echo ==========================================================
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] No existe el entorno virtual .venv.
    echo Usa primero "Abrir Email Scraper.bat" para la instalacion inicial.
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo La app se abrira en: http://localhost:8501
echo Para PARAR la app: cierra esta ventana o pulsa Ctrl+C.
echo.

start "" cmd /c "timeout /t 6 >nul & start http://localhost:8501"

python -m streamlit run app.py

echo.
echo La app se ha detenido.
pause
