@echo off
setlocal
cd /d "D:\Rodrigo\FinanzIAs\FinanzIAs"

echo Instalando la tarea programada del dashboard ...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup_dashboard_schedule.ps1"
if errorlevel 1 (
  echo.
  echo *** FALLO al instalar la tarea ***
  pause
  exit /b 1
)
echo.
pause
