param([switch]$Preparar)
$ErrorActionPreference = 'Stop'
$raizProjeto = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $raizProjeto
$pythonProjeto = Join-Path $raizProjeto '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonProjeto)) {
    throw 'Crie .venv e instale requirements-dev.txt conforme docs/testes_locais.md.'
}
$env:DJANGO_SETTINGS_MODULE = 'config.settings.local'
if ($Preparar) {
    & $pythonProjeto manage.py migrate
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao migrar banco local.' }
    & $pythonProjeto manage.py seed_inicial
    if ($LASTEXITCODE -ne 0) { throw 'Falha na carga inicial.' }
    & $pythonProjeto manage.py preparar_demo
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar acesso local.' }
}
& $pythonProjeto manage.py runserver 127.0.0.1:8000 --noreload
