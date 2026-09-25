# Webfänger

Webfänger lädt die Bilder einer Webseite in einen Ordner herunter. Die App
ist eine einzelne `Webfaenger.exe` (ca. 10 MB) und braucht keine Installation.

## Benutzung

1. `Webfaenger.exe` starten.
2. URL der Webseite einfügen (Strg+V oder Rechtsklick > Einfügen) und
   auf „Bilder suchen“ klicken.
3. Die Übersicht zeigt, wie viele Bilder gefunden wurden. Mit
   „Herunterladen“ werden sie im Zielordner gespeichert.

Unter „Einstellungen anzeigen“ lassen sich Dateitypen, Mindestgröße und
Dateinamen einstellen. Die Einstellungen bleiben gespeichert
(`%APPDATA%\Webfaenger\settings.json`).

Beim ersten Start kann Windows SmartScreen warnen („Unbekannter
Herausgeber“), weil die Datei nicht signiert ist. Über „Weitere
Informationen“ > „Trotzdem ausführen“ startet sie.

Webfänger liest nur Bilder, die im HTML der Seite stehen. Seiten, die ihre
Bilder erst per JavaScript nachladen, werden noch nicht unterstützt.

## Entwicklung

Voraussetzung ist Python 3.11 oder neuer. Die App nutzt nur die
Standardbibliothek.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest            # Tests
.venv\Scripts\python.exe -m webfaenger        # Oberfläche starten
.venv\Scripts\python.exe -m webfaenger URL -o Ordner   # Kommandozeile
```

`.exe` bauen (landet in `dist\Webfaenger.exe`):

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Das Icon wird mit `python tools/make_icon.py` neu erzeugt.
