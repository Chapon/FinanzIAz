@echo off
rem Abre FinanzIAs con el Python del .venv del repo (tarea 401): es el entorno del
rem lock y del CI. Hasta el 2026-10-26 la app corria en la Anaconda, con 37 versiones
rem distintas de las probadas.
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" goto sin_venv

"%PY%" main.py %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" exit /b 0
echo.
echo *** FinanzIAs salio con error %RC%: mira %USERPROFILE%\.finanzias\finanzias.log ***
pause
exit /b %RC%

:sin_venv
echo *** No esta el .venv del repo: %CD%\.venv ***
echo Crealo con: python -m venv .venv  y despues  .venv\Scripts\pip install -r requirements.lock
pause
exit /b 1
