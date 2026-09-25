<p align="center"><img src="webfaenger/assets/icon.png" width="96" alt=""></p>

# Webfänger

Webfänger findet die Bilder einer Webseite, zeigt sie als Vorschau und
speichert die ausgewählten in einen Ordner. Die App läuft unter Windows 10
und 11.

## Installation

1. Unter [Releases](https://github.com/phuelsebus/webfaenger/releases) die
   neueste `Webfaenger-Setup-….exe` herunterladen.
2. Die Datei doppelt anklicken und dem Assistenten folgen. Administratorrechte
   sind nicht nötig.
3. Webfänger steht danach im Startmenü.

**Warnung „Der Computer wurde durch Windows geschützt“:** Windows zeigt sie
bei Programmen, die nicht mit einem kostenpflichtigen Zertifikat signiert
sind. Auf „Weitere Informationen“ klicken, dann auf „Trotzdem ausführen“.

Wer nichts installieren möchte, lädt stattdessen `Webfaenger-portable.exe`
herunter und startet sie direkt.

Die Oberfläche braucht die Microsoft Edge WebView2-Laufzeit. Sie ist in
Windows 11 enthalten; auf älteren Windows-10-Rechnern lädt der Installer sie
bei Bedarf von Microsoft nach.

**Deinstallieren:** Einstellungen > Apps > Installierte Apps > Webfänger.

## Benutzung

1. URL der Webseite einfügen und auf „Bilder suchen“ klicken.
2. Die gefundenen Bilder erscheinen als Vorschau. Ein Klick wählt ein Bild
   ab oder wieder an, die Lupe zeigt es groß. Oben lassen sich Dateitypen
   und kleine Bilder ausblenden.
3. „Bilder speichern“ schreibt die ausgewählten Bilder in den Zielordner.

Jede Suche bekommt einen eigenen Unterordner, benannt nach der URL:
`https://www.bild.de/` landet in `bildde`, eine zweite Suche auf derselben
Seite in `bildde_2`. Die Option lässt sich unter dem Zielordner abschalten.

Über das Symbol oben rechts lassen sich die Dateinamen einstellen. Alle
Einstellungen bleiben gespeichert (`%APPDATA%\Webfaenger\settings.json`).
Hell und Dunkel folgen der Windows-Einstellung.

Webfänger liest die Bilder, die im HTML einer Seite stehen, auch solche in
eingebetteten Skript-Daten. Seiten, die ihre Bilder erst beim Scrollen per
JavaScript nachladen, und Seiten mit Anmeldung werden nicht unterstützt.

**Probleme melden:** Bitte ein
[Issue](https://github.com/phuelsebus/webfaenger/issues) anlegen und die URL
nennen, die nicht funktioniert. Das Protokoll
(`%LOCALAPPDATA%\Webfaenger\webfaenger.log`, erreichbar über Einstellungen >
„Protokollordner öffnen“) hilft bei der Fehlersuche.

Bilder auf Webseiten sind meist urheberrechtlich geschützt. Wofür
heruntergeladene Bilder verwendet werden dürfen, liegt in der Verantwortung
der Nutzerin oder des Nutzers.

## Entwicklung

Voraussetzung ist Python 3.11 oder neuer. Der Kern (Suche, Laden,
Speichern) nutzt nur die Standardbibliothek, die Oberfläche braucht
pywebview.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install pytest pywebview
.venv\Scripts\python.exe -m pytest            # Tests
.venv\Scripts\python.exe -m webfaenger        # Oberfläche starten
.venv\Scripts\python.exe -m webfaenger URL -o Ordner   # Kommandozeile
```

Weitergabe bauen (braucht [Inno Setup 6](https://jrsoftware.org/isinfo.php),
z. B. `winget install JRSoftware.InnoSetup`):

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Das Skript führt die Tests aus und legt in `dist\` den Installer, die
portable `.exe` und den Programmordner ab. Die Versionsnummer steht in
`webfaenger/__init__.py`.

Das Icon (Spinnennetz, das ein Foto heranzieht) ist als SVG in
`tools/make_icon.py` beschrieben. `python tools/make_icon.py` rendert es
mit Microsoft Edge in alle Icon-Größen und schreibt `icon.ico` und
`icon.png`; das Vektor-Logo liegt in `webfaenger/assets/logo.svg`.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
