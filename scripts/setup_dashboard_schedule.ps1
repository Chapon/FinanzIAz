# Registra (o reemplaza) la tarea de Windows que refresca el dashboard cada manana.
# Hardening: StartWhenAvailable => si la PC estaba apagada a la hora programada,
# la tarea corre sola apenas se enciende y el usuario inicia sesion (catch-up).
# Corre como el usuario actual, en sesion interactiva => no requiere admin ni
# guardar contrasena. Volve a ejecutar este script para cambiar la hora.

$ErrorActionPreference = "Stop"

# --- Config editable ---
$repo     = "D:\Rodrigo\FinanzIAs\FinanzIAs"
$hora     = "8:00am"                       # <-- cambia la hora aca
$taskName = "FinanzIAs - Refrescar Dashboard"
# -----------------------

$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$script = Join-Path $repo "scripts\refresh_dashboard.py"
if (-not (Test-Path $script)) {
    Write-Host "ERROR: no encuentro $script" -ForegroundColor Red
    exit 1
}

$action = New-ScheduledTaskAction -Execute $py `
    -Argument "scripts\refresh_dashboard.py" `
    -WorkingDirectory $repo

$trigger = New-ScheduledTaskTrigger -Daily -At $hora

# StartWhenAvailable        => catch-up si se perdio la corrida (PC apagada).
# DontStopIfGoingOnBatteries / AllowStartIfOnBatteries => corre en notebook con bateria.
# RestartCount/Interval     => reintenta si falla (ej: DB ocupada un instante).
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Genera snapshot fresco de finanzias.db e inyecta el const DATA en el index.html del artifact del dashboard. StartWhenAvailable: corre al encender si la PC estaba apagada a la hora programada." `
    -Force | Out-Null

Write-Host ""
Write-Host "OK - tarea registrada: '$taskName'" -ForegroundColor Green
Write-Host "    Corre todos los dias a las $hora (y al encender si estaba apagada)."
Write-Host "    Python: $py"
Write-Host ""
Write-Host "Para probarla ahora mismo:" -ForegroundColor Cyan
Write-Host "    Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Para verla / borrarla: abri 'Programador de tareas' (taskschd.msc)."
