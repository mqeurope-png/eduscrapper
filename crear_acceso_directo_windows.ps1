# Crea un acceso directo en el Escritorio que apunta a "Abrir Email Scraper.bat".
# Uso: clic derecho sobre este archivo -> "Ejecutar con PowerShell".
# Si Windows lo bloquea, abre PowerShell en esta carpeta y ejecuta:
#   powershell -ExecutionPolicy Bypass -File .\crear_acceso_directo_windows.ps1

$ErrorActionPreference = "Stop"

$appDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$target   = Join-Path $appDir "Abrir Email Scraper.bat"
$desktop  = [Environment]::GetFolderPath("Desktop")
$lnkPath  = Join-Path $desktop "Email Scraper.lnk"

if (-not (Test-Path $target)) {
    Write-Host "[ERROR] No se encontro 'Abrir Email Scraper.bat' en $appDir" -ForegroundColor Red
    Read-Host "Pulsa Enter para salir"
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnkPath)
$sc.TargetPath       = $target
$sc.WorkingDirectory = $appDir
$sc.WindowStyle      = 1
$sc.Description       = "Abrir Email Scraper"
$sc.Save()

Write-Host "[OK] Acceso directo creado en el Escritorio: 'Email Scraper'" -ForegroundColor Green
Read-Host "Pulsa Enter para salir"
