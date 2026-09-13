param()
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:TEMP = Join-Path $projectRoot '.tmp'
$env:TMP = $env:TEMP
$env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot '.tmp\pyinstaller-cache'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$assets = (Join-Path $projectRoot 'src\deepseek_survey\web_assets') + ';deepseek_survey\web_assets'
& $python -m PyInstaller --noconfirm --windowed --onedir --name PaperAtlas --paths src --add-data $assets --distpath dist --workpath .tmp\pyinstaller-build --specpath .tmp desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
$appDirectory = Join-Path $projectRoot 'dist\PaperAtlas'
Copy-Item -LiteralPath (Join-Path $projectRoot 'config.toml') -Destination $appDirectory
$codexCommand = Get-Command codex -ErrorAction Stop
$codexDirectory = Split-Path -Parent $codexCommand.Source
# Keep the official binary and its companion runtime files together; no user credentials are copied.
$codexDestination = Join-Path $appDirectory 'codex'
New-Item -ItemType Directory -Force -Path $codexDestination | Out-Null
Get-ChildItem -LiteralPath $codexDirectory | Copy-Item -Destination $codexDestination -Recurse -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\desktop-app.md') -Destination (Join-Path $appDirectory 'README.zh-CN.md')
$smoke = Start-Process -FilePath (Join-Path $appDirectory 'PaperAtlas.exe') -ArgumentList '--smoke-test' -Wait -PassThru -WindowStyle Hidden
if ($smoke.ExitCode -ne 0) { throw 'Packaged smoke test failed.' }
Write-Output (Join-Path $appDirectory 'PaperAtlas.exe')
