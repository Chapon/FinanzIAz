@echo off
setlocal
cd /d "D:\Rodrigo\FinanzIAs\FinanzIAs"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo Generando snapshot fresco desde finanzias.db ...
"%PY%" scripts\refresh_dashboard.py
if errorlevel 1 (
  echo.
  echo *** FALLO al refrescar el dashboard ***
  pause
  exit /b 1
)
echo.
echo Listo. Reabri el artifact del dashboard.
pause
