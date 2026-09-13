param([int]$Port = 8765)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment missing. Follow the setup steps in README.md first.'
}
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:TEMP = Join-Path $projectRoot '.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
& $python -m deepseek_survey.web --runs (Join-Path $projectRoot 'runs') --config (Join-Path $projectRoot 'config.toml') --port $Port
exit $LASTEXITCODE
