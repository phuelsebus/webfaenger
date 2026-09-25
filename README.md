# Webfänger

Webfänger lädt die Bilder einer Webseite in einen Ordner herunter. Die App
ist eine einzelne `Webfaenger.exe` (ca. 13 MB) und braucht keine Installation.
Die Oberfläche läuft im Edge-WebView2, das in Windows 11 eingebaut ist. Fehlt
es (ältere Windows-10-Systeme), weist die App beim Start darauf hin.

## Benutzung

1. `Webfaenger.exe` starten.
2. URL der Webseite einfügen und auf „Bilder suchen“ klicken.
3. Die gefundenen Bilder erscheinen als Vorschau. Ein Klick wählt ein Bild
   ab oder wieder an, die Lupe zeigt es groß. Oben lassen sich Dateitypen
   und kleine Bilder ausblenden.
4. „Bilder speichern“ schreibt die ausgewählten Bilder in den Zielordner.

Jede Suche bekommt einen eigenen Unterordner im Zielordner, benannt nach
der URL: `https://www.bild.de/` landet in `bildde`, eine zweite Suche auf
derselben Seite in `bildde_2`. Die Option lässt sich unter dem Zielordner
abschalten.

Über das Symbol oben rechts lassen sich die Dateinamen einstellen. Alle
Einstellungen bleiben gespeichert (`%APPDATA%\Webfaenger\settings.json`).
Hell und Dunkel folgen der Windows-Einstellung.

Beim ersten Start kann Windows SmartScreen warnen („Unbekannter
Herausgeber“), weil die Datei nicht signiert ist. Über „Weitere
Informationen“ > „Trotzdem ausführen“ startet sie.

Webfänger liest nur Bilder, die im HTML der Seite stehen. Seiten, die ihre
Bilder erst per JavaScript nachladen, werden noch nicht unterstützt.

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

`.exe` bauen (landet in `dist\Webfaenger.exe`):

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Das Icon (Spinnennetz, das ein Foto heranzieht) ist als SVG in
`tools/make_icon.py` beschrieben. `python tools/make_icon.py` rendert es
mit Microsoft Edge in alle Icon-Größen und schreibt `icon.ico` und
`icon.png`; das Vektor-Logo liegt in `webfaenger/assets/logo.svg`.
