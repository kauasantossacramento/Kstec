$ErrorActionPreference = 'Stop'
$raizProjeto = Split-Path -Parent $PSScriptRoot
$pastaFerramentas = Join-Path $raizProjeto '.tools'
New-Item -ItemType Directory -Path $pastaFerramentas -Force | Out-Null
$arquivoPdfZip = Join-Path $pastaFerramentas 'weasyprint.zip'
$destinoPdf = Join-Path $pastaFerramentas 'weasyprint'
# Distribuição oficial, com a mesma versão fixada em requirements.txt.
Invoke-WebRequest -Uri 'https://github.com/Kozea/WeasyPrint/releases/download/v70.0/weasyprint-windows-onedir.zip' -OutFile $arquivoPdfZip
Expand-Archive -LiteralPath $arquivoPdfZip -DestinationPath $destinoPdf -Force
& (Join-Path $destinoPdf 'onedir\weasyprint\weasyprint.exe') --info
if ($LASTEXITCODE -ne 0) { throw 'Falha na verificação do WeasyPrint portátil.' }
