# Baut Webfaenger fuer die Weitergabe. Ergebnis in dist\:
#   Webfaenger-Setup-<version>.exe   Installer (Startmenue, Deinstallation, ohne Adminrechte)
#   Webfaenger-portable.exe          einzelne Datei zum direkten Starten
#   Webfaenger\                      Programmordner, aus dem der Installer entsteht
#
# Aufruf im Projektordner:  powershell -ExecutionPolicy Bypass -File build.ps1
# Fuer den Installer muss Inno Setup 6 installiert sein (winget install JRSoftware.InnoSetup).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Keine .venv gefunden. Erst anlegen: python -m venv .venv"
    exit 1
}

& $python -m pip install --quiet --disable-pip-version-check pyinstaller pywebview pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "Tests fehlgeschlagen, Build abgebrochen."; exit 1 }

# Alte Einzeldatei frueherer Builds entfernen, damit dist\ nur aktuelle Dateien enthaelt
if (Test-Path dist\Webfaenger.exe) { Remove-Item dist\Webfaenger.exe }

$version = & $python tools\version_info.py build\version_info.txt
Write-Host "Version $version"

# Module, die die App nie braucht, bleiben draussen und halten die Dateien klein.
$exclude = @("tkinter", "_tkinter", "unittest", "pydoc", "doctest", "pdb", "sqlite3",
             "xmlrpc", "asyncio", "pytest", "_pytest")
$common = @(
    "--noconfirm", "--clean", "--windowed",
    "--icon", "webfaenger\assets\icon.ico",
    "--version-file", "build\version_info.txt",
    "--add-data", "webfaenger\assets;webfaenger\assets",
    "--add-data", "webfaenger\web;webfaenger\web",
    "--specpath", "build"
)
foreach ($m in $exclude) { $common += @("--exclude-module", $m) }
# --specpath build: relative Pfade gelten dann ab build\, daher absolute Pfade setzen
$common = $common | ForEach-Object { if ($_ -like "webfaenger\*" -or $_ -like "build\version*") { Join-Path $PSScriptRoot $_ } else { $_ } }

# 1) Programmordner fuer den Installer (startet schneller als die Einzeldatei)
& $python -m PyInstaller @common --onedir --name Webfaenger --workpath build\onedir run_webfaenger.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 2) Portable Einzeldatei
& $python -m PyInstaller @common --onefile --name Webfaenger-portable --workpath build\onefile run_webfaenger.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 3) Installer
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q "/DAppVersion=$version" installer\webfaenger.iss
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "Inno Setup nicht gefunden, Installer wird uebersprungen."
}

Get-ChildItem dist -File | ForEach-Object {
    Write-Host ("Fertig: {0} ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
}
$folder = (Get-ChildItem dist\Webfaenger -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("Fertig: Webfaenger\ ({0:N1} MB)" -f ($folder / 1MB))
