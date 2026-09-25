# Baut dist\Webfaenger.exe (eine Datei, ohne Konsole, mit Icon).
# Aufruf im Projektordner:  powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Keine .venv gefunden. Erst anlegen: python -m venv .venv"
    exit 1
}

& $python -m pip install --quiet --disable-pip-version-check pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "Tests fehlgeschlagen, Build abgebrochen."; exit 1 }

# Module, die die App nie braucht, bleiben draußen und halten die .exe klein.
$exclude = @("unittest", "pydoc", "doctest", "pdb", "sqlite3", "xmlrpc",
             "multiprocessing", "asyncio", "pytest", "_pytest")

$pyiArgs = @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "Webfaenger",
    "--icon", "webfaenger\assets\icon.ico",
    "--add-data", "webfaenger\assets;webfaenger\assets"
)
foreach ($m in $exclude) { $pyiArgs += @("--exclude-module", $m) }

& $python -m PyInstaller @pyiArgs run_webfaenger.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Get-Item "dist\Webfaenger.exe"
Write-Host ("Fertig: {0} ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB))
