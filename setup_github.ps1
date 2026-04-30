# ─────────────────────────────────────────────────────────────────────
# FinanzIAs — Sincronización inicial con GitHub
# Ejecutar desde D:\Rodrigo\FinanzIAs\FinanzIAs en PowerShell
#
# Requisitos:
#   - Git instalado (https://git-scm.com/download/win)
#   - Un Personal Access Token (PAT) de GitHub:
#       https://github.com/settings/tokens  →  "Generate new token (classic)"
#       Permisos mínimos: repo
#       Copialo y guardalo en un lugar seguro (solo se muestra una vez).
# ─────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "==> Limpiando .git previa (si quedó corrupta)..." -ForegroundColor Cyan
if (Test-Path ".git") {
    Remove-Item -Recurse -Force ".git"
}

Write-Host "==> git init..." -ForegroundColor Cyan
git init -b main

Write-Host "==> Configurando usuario local..." -ForegroundColor Cyan
git config user.email "chapa1234@gmail.com"
git config user.name  "Chapon"

Write-Host "==> Agregando archivos (respetando .gitignore)..." -ForegroundColor Cyan
git add .

Write-Host "==> Primer commit..." -ForegroundColor Cyan
git commit -m "Initial commit: FinanzIAs investment tracker"

Write-Host "==> Configurando remote origin..." -ForegroundColor Cyan
git remote remove origin 2>$null
git remote add origin https://github.com/Chapon/FinanzIAz.git

Write-Host ""
Write-Host "✓ Repositorio local listo." -ForegroundColor Green
Write-Host ""
Write-Host "=========================================================="
Write-Host "PUSH A GITHUB"
Write-Host "=========================================================="
Write-Host "Ejecutá:"
Write-Host "    git push -u origin main" -ForegroundColor Yellow
Write-Host ""
Write-Host "Cuando pida credenciales:"
Write-Host "    Username: Chapon"
Write-Host "    Password: <pegá tu Personal Access Token, NO tu contraseña>"
Write-Host ""
Write-Host "Para evitar pegarlo cada vez, podés usar:"
Write-Host "    git config --global credential.helper manager" -ForegroundColor Yellow
Write-Host "(Git Credential Manager guarda el PAT en Windows Credential Store)"
Write-Host "=========================================================="
