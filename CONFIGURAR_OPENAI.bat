@echo off
setlocal
title Configurar OpenAI

cd /d "%~dp0"

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo Se ha creado .env desde .env.example.
    )
)

if not exist ".env" (
    echo [ERROR] No existe .env ni .env.example en esta carpeta.
    pause
    exit /b 1
)

echo Abriendo .env en el Bloc de notas.
echo Pega tu clave en la linea OPENAI_API_KEY= y guarda con Ctrl+S.
echo Sin clave, la app funciona igual en modo solo scraping.
notepad .env
