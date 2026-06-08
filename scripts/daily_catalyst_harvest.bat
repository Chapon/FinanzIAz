@echo off
REM ── FinanzIAs · Sprint 5 Catalyst Engine ──────────────────────────────────
REM Daily point-in-time harvest (T-CAT-0/1) + classification (T-CAT-2).
REM Run by Windows Task Scheduler ~18:30 ART (post NY close).
REM
REM SEC_EDGAR_USER_AGENT is read from the persistent user environment
REM (set once with: setx SEC_EDGAR_USER_AGENT "FinanzIAs you@example.com").
REM No secrets live in this file, so it's safe to commit.
REM
REM Register the task (one time, normal terminal — no admin needed):
REM   schtasks /Create /TN "FinanzIAs Catalyst Harvest" ^
REM     /TR "D:\Rodrigo\FinanzIAs\FinanzIAs\scripts\daily_catalyst_harvest.bat" ^
REM     /SC DAILY /ST 18:30 /F
REM Inspect / run / remove:
REM   schtasks /Query /TN "FinanzIAs Catalyst Harvest"
REM   schtasks /Run   /TN "FinanzIAs Catalyst Harvest"
REM   schtasks /Delete /TN "FinanzIAs Catalyst Harvest" /F
REM ───────────────────────────────────────────────────────────────────────────

setlocal
set REPO=D:\Rodrigo\FinanzIAs\FinanzIAs
set PY=C:\Users\chapa\anaconda3\python.exe
set LOG=%USERPROFILE%\.finanzias\catalyst_harvest.log

cd /d "%REPO%"
echo. >> "%LOG%"
echo ===== %DATE% %TIME% catalyst harvest start ===== >> "%LOG%"
"%PY%" scripts\harvest_catalysts.py --sources yfinance,sec >> "%LOG%" 2>&1
"%PY%" scripts\classify_catalysts.py >> "%LOG%" 2>&1
echo ===== %DATE% %TIME% catalyst harvest done ===== >> "%LOG%"
endlocal
