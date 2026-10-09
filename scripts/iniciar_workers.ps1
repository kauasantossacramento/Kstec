# Sobe, nesta máquina Windows, os processos que em produção são serviços do docker compose:
#   Celery worker (pool solo), Celery beat e o worker do WhatsApp.
# Requer Redis local (Memurai, WSL ou "docker run -p 6379:6379 redis:7-alpine") e KSCENTRAL_REDIS=True no .env.
# Uso:  .\scripts\iniciar_workers.ps1            (Celery + beat + WhatsApp)
#       .\scripts\iniciar_workers.ps1 -SemZap    (sem o WhatsApp)
#       .\scripts\iniciar_workers.ps1 -ZapSimulado (WhatsApp sem conectar ao celular)
param([switch]$SemZap, [switch]$ZapSimulado)
$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $raiz
$py = Join-Path $raiz '.venv\Scripts\python.exe'
$env:DJANGO_SETTINGS_MODULE = 'config.settings.local'
$env:KSCENTRAL_REDIS = 'True'

& $py -c "import redis,os; redis.Redis.from_url(os.environ.get('REDIS_URL','redis://localhost:6379/0')).ping()"
if ($LASTEXITCODE -ne 0) { throw 'Redis não respondeu em localhost:6379. Inicie o Redis antes.' }

$logs = Join-Path $raiz 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
Start-Process -FilePath $py -ArgumentList '-m','celery','-A','config','worker','-P','solo','-l','info' `
    -WorkingDirectory $raiz -WindowStyle Hidden -RedirectStandardOutput "$logs\celery-worker.log" -RedirectStandardError "$logs\celery-worker.err.log"
Start-Process -FilePath $py -ArgumentList '-m','celery','-A','config','beat','-l','info' `
    -WorkingDirectory $raiz -WindowStyle Hidden -RedirectStandardOutput "$logs\celery-beat.log" -RedirectStandardError "$logs\celery-beat.err.log"
if (-not $SemZap) {
    $argsZap = @('manage.py','whatsapp_worker')
    if ($ZapSimulado) { $argsZap += '--simulado' }
    Start-Process -FilePath $py -ArgumentList $argsZap -WorkingDirectory $raiz -WindowStyle Hidden `
        -RedirectStandardOutput "$logs\whatsapp.log" -RedirectStandardError "$logs\whatsapp.err.log"
}
Write-Host 'Processos iniciados. Logs em .\logs. Reinicie o runserver com KSCENTRAL_REDIS=True para compartilhar o mesmo cache.'
Write-Host 'Para encerrar: Get-CimInstance Win32_Process -Filter "Name=''python.exe''" | ? CommandLine -match ''celery|whatsapp_worker'' | % { Stop-Process $_.ProcessId }'
