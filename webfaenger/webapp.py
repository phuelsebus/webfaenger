"""Oberfläche mit pywebview: HTML/CSS/JS im Edge-Webview (WebView2).

Python erledigt Suche, Laden und Speichern in Hintergrundthreads und sammelt
Ereignisse, die die Seite alle 150 ms mit `poll()` abholt. Vorschaubilder
liefert ein kleiner HTTP-Server auf 127.0.0.1 direkt aus dem Arbeitsspeicher.
Ein Zufallstoken im Pfad hält andere Programme auf dem Rechner davon ab, ihn
zu benutzen.
"""

from __future__ import annotations

import os
import secrets
import threading
from dataclasses import asdict, fields
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import settings as settings_mod
from .downloader import FetchedImage, Fetcher, save_images
from .models import IMAGE_TYPES
from .naming import (Collision, NameContext, NamingMode, NamingOptions, build_stem,
                     folder_name, original_stem, unique_folder, validate_pattern)
from .net import FetchError
from .scraper import normalize_url, scan
from .summary import report_summary
from .winstyle import (WEBVIEW2_DOWNLOAD, message_box, set_titlebar_dark,
                       system_prefers_dark, webview2_installed)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_FILES = {
    "index.html": (PACKAGE_DIR / "web" / "index.html", "text/html; charset=utf-8"),
    "app.js": (PACKAGE_DIR / "web" / "app.js", "text/javascript; charset=utf-8"),
    "style.css": (PACKAGE_DIR / "web" / "style.css", "text/css; charset=utf-8"),
    "icon.png": (PACKAGE_DIR / "assets" / "icon.png", "image/png"),
}
IMAGE_MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp",
              "gif": "image/gif", "svg": "image/svg+xml", "avif": "image/avif",
              "bmp": "image/bmp", "ico": "image/x-icon", "tiff": "image/tiff"}
COLLISIONS = [(Collision.RENAME.value, "Neuen Namen vergeben (bild_1.jpg)"),
              (Collision.OVERWRITE.value, "Vorhandene Datei überschreiben"),
              (Collision.SKIP.value, "Bild überspringen")]
BACKGROUND = {True: "#111113", False: "#F3F4F6"}  # vor dem ersten Zeichnen der Seite


class Api:
    """Funktionen für die Seite (window.pywebview.api.*).

    pywebview reicht alle öffentlichen Attribute an JavaScript weiter; interner
    Zustand beginnt deshalb durchgehend mit einem Unterstrich."""

    def __init__(self) -> None:
        self._settings = settings_mod.load()
        self._token = secrets.token_urlsafe(18)
        self._window = None
        self._hwnd = 0
        self._dark = system_prefers_dark()
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._scan_id = 0
        self._scan_url = ""
        self._page_url = ""
        self._images: dict[int, FetchedImage] = {}
        self._fetcher: Fetcher | None = None
        self._busy = False
        self._search_folder: Path | None = None
        self._last_folder: Path | None = None

    # ------------------------------------------------------------ intern

    def _emit(self, **event) -> None:
        with self._lock:
            self._events.append(event)

    def _image(self, scan_id: str, image_id: str) -> FetchedImage | None:
        if scan_id != str(self._scan_id) or not image_id.isdigit():
            return None
        return self._images.get(int(image_id))

    def _target_folder(self, folder: str, subfolder: bool) -> Path | None:
        """Zielordner, mit Unterordner pro Suche (z. B. …/Webfänger/bildde)."""
        folder = folder.strip()
        if not folder:
            return None
        base = Path(folder).expanduser()
        if not subfolder:
            return base
        if not self._scan_url:
            return None
        # Einmal pro Suche festgelegt: ein zweites Speichern landet im selben Ordner.
        if self._search_folder is None or self._search_folder.parent != base:
            return unique_folder(base, folder_name(self._scan_url))
        return self._search_folder

    def _naming(self, naming: dict) -> NamingOptions:
        mode = naming.get("mode", "original")
        collision = naming.get("collision", "rename")
        return NamingOptions(
            mode=NamingMode(mode) if mode in NamingMode._value2member_map_ else NamingMode.ORIGINAL,
            prefix=str(naming.get("prefix", "")).strip(), pattern=str(naming.get("pattern", "")),
            collision=Collision(collision) if collision in Collision._value2member_map_
            else Collision.RENAME)

    # ------------------------------------------------------- für die Seite

    def init(self) -> dict:
        forced = os.environ.get("WEBFAENGER_THEME")  # "light"/"dark", sonst wie Windows
        return {"settings": asdict(self._settings), "types": list(IMAGE_TYPES),
                "collisions": COLLISIONS, "theme": forced if forced in ("light", "dark") else None}

    def poll(self) -> list[dict]:
        with self._lock:
            events, self._events = self._events, []
        return events

    def scan(self, raw_url: str) -> dict:
        if self._busy:
            return {"error": "Es läuft bereits eine Suche."}
        try:
            url = normalize_url(raw_url)
        except ValueError as exc:
            return {"error": str(exc)}
        self._scan_id += 1
        self._scan_url, self._page_url = url, url
        self._images, self._search_folder, self._busy = {}, None, True
        self._fetcher = None
        threading.Thread(target=self._scan_worker, args=(self._scan_id, url), daemon=True).start()
        return {"ok": True, "url": url, "scanId": self._scan_id}

    def _scan_worker(self, scan_id: int, url: str) -> None:
        try:
            result = scan(url)
        except (ValueError, FetchError) as exc:
            error = str(exc)
        except Exception as exc:  # nie mit hängender Oberfläche enden
            error = f"Unerwarteter Fehler: {exc}"
        else:
            error = None
        if scan_id != self._scan_id:
            return  # inzwischen abgebrochen oder neue Suche
        if error:
            self._busy = False
            self._emit(type="scan_error", scanId=scan_id, message=error)
            return

        self._page_url = result.page_url
        self._emit(type="scan_done", scanId=scan_id, count=len(result.candidates),
                   host=urlsplit(result.page_url).hostname or result.page_url)

        def on_item(item: FetchedImage, done: int, total: int) -> None:
            if item.status == "ok":
                self._images[item.id] = item
            self._emit(type="item", scanId=scan_id, done=done, total=total, id=item.id,
                       status=item.status, imgType=item.img_type, size=item.size,
                       name=original_stem(item.url) or item.url, url=item.url,
                       error=item.error)

        self._fetcher = Fetcher(on_item=on_item)
        items = self._fetcher.run(result.page_url, result.candidates)
        counts = {s: sum(i.status == s for i in items)
                  for s in ("ok", "duplicate", "notimage", "error", "cancelled")}
        self._busy = False
        self._emit(type="fetch_done", scanId=scan_id, counts=counts,
                   cancelled=self._fetcher.cancelled)

    def cancel(self) -> None:
        if self._fetcher and self._busy:
            self._fetcher.cancel()
        elif self._busy:  # noch in der Seitensuche: Ergebnis verwerfen
            self._scan_id += 1
            self._busy = False
            self._emit(type="scan_error", scanId=self._scan_id, message="Suche abgebrochen.")

    def preview_name(self, naming: dict) -> dict:
        options = self._naming(naming)
        if options.mode is NamingMode.PATTERN and (error := validate_pattern(options.pattern)):
            return {"error": error}
        sample = next(iter(self._images.values()), None)
        ctx = NameContext(url=sample.url if sample else "https://example.com/bilder/sonnenuntergang.jpg",
                          page_url=self._page_url or "https://example.com/", index=options.start,
                          digest=(sample.digest if sample else None) or "3f2a9c1be07d" + "0" * 28,
                          when=datetime.now())
        return {"name": f"{build_stem(options, ctx)}.{sample.img_type if sample else 'jpg'}"}

    def target_folder(self, folder: str, subfolder: bool) -> dict:
        target = self._target_folder(folder, subfolder)
        return {"path": str(target) if target else "", "name": target.name if target else ""}

    def choose_folder(self, current: str) -> str | None:
        import webview
        start = current if current and Path(current).is_dir() else str(Path.home())
        chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        return str(Path(chosen[0])) if chosen else None

    def save(self, request: dict) -> dict:
        if self._busy:
            return {"error": "Bitte warten, bis die Vorschau fertig geladen ist."}
        ids = sorted({int(i) for i in request.get("ids", []) if str(i).isdigit()})
        items = [self._images[i] for i in ids if i in self._images]
        if not items:
            return {"error": "Keine Bilder ausgewählt."}
        naming = self._naming(request.get("naming", {}))
        if naming.mode is NamingMode.PATTERN and (error := validate_pattern(naming.pattern)):
            return {"error": f"Das Namensmuster funktioniert so nicht: {error}"}
        folder = self._target_folder(str(request.get("folder", "")),
                                     bool(request.get("subfolder")))
        if folder is None:
            return {"error": "Kein Zielordner angegeben. Bitte über „Durchsuchen…“ einen "
                             "Ordner wählen."}
        if request.get("subfolder"):
            self._search_folder = folder
        self._last_folder, self._busy = folder, True
        threading.Thread(target=self._save_worker, args=(items, folder, naming),
                         daemon=True).start()
        return {"ok": True, "folder": str(folder)}

    def _save_worker(self, items: list[FetchedImage], folder: Path,
                     naming: NamingOptions) -> None:
        try:
            report = save_images(items, page_url=self._page_url, folder=folder, naming=naming,
                                 on_progress=lambda done, total, msg: self._emit(
                                     type="save_progress", done=done, total=total, message=msg))
        except OSError:
            report = None
        self._busy = False
        if report is None:
            self._emit(type="save_error", message="Der Zielordner lässt sich nicht anlegen. "
                                                  "Bitte einen anderen Ordner wählen.")
            return
        self._emit(type="save_done", summary=report_summary(report), folder=str(folder),
                   saved=len(report.saved), failed=[f"{u} ({e})" for u, e in report.failed])

    def open_folder(self) -> dict:
        if self._last_folder and self._last_folder.is_dir():
            os.startfile(self._last_folder)  # noqa: S606 – öffnet den Explorer
            return {"ok": True}
        return {"error": "Den Ordner gibt es noch nicht. Er wird beim ersten Speichern angelegt."}

    def save_settings(self, data: dict) -> None:
        defaults = settings_mod.Settings()
        for f in fields(settings_mod.Settings):
            if f.name in data and isinstance(data[f.name], type(getattr(defaults, f.name))):
                setattr(self._settings, f.name, data[f.name])
        settings_mod.save(self._settings)

    # --------------------------------------------------------- Fenster

    def _on_shown(self) -> None:
        try:
            self._hwnd = int(self._window.native.Handle.ToInt64())
        except Exception:
            self._hwnd = 0
        forced = os.environ.get("WEBFAENGER_THEME")
        if forced in ("light", "dark"):
            self._dark = forced == "dark"
        set_titlebar_dark(self._hwnd, self._dark)
        self._set_window_icon()
        if forced not in ("light", "dark"):
            threading.Thread(target=self._watch_theme, daemon=True).start()

    def _set_window_icon(self) -> None:
        """In der .exe kommt das Icon aus der Datei; beim Start aus Python hier setzen."""
        try:
            from System import Action  # pythonnet, von pywebview mitgebracht
            from System.Drawing import Icon
            form = self._window.native
            icon = Icon(str(PACKAGE_DIR / "assets" / "icon.ico"))
            form.Invoke(Action(lambda: setattr(form, "Icon", icon)))
        except Exception:
            pass

    def _watch_theme(self) -> None:
        """Die Seite folgt dem Systemdesign per CSS; die Titelleiste hier."""
        import time
        while self._window is not None:
            time.sleep(1.5)
            dark = system_prefers_dark()
            if dark != self._dark:
                self._dark = dark
                set_titlebar_dark(self._hwnd, dark)

    def _on_closing(self) -> bool:
        if self._busy and self._window is not None:
            if not self._window.create_confirmation_dialog(
                    "Webfänger", "Es läuft noch ein Vorgang. Trotzdem schließen?\n\n"
                                 "Bereits gespeicherte Bilder bleiben erhalten."):
                return False
            if self._fetcher:
                self._fetcher.cancel()
        settings_mod.save(self._settings)
        return True


class _Handler(BaseHTTPRequestHandler):
    api: Api  # wird in _start_server gesetzt

    def do_GET(self) -> None:  # noqa: N802 – Name von BaseHTTPRequestHandler
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if len(parts) < 2 or not secrets.compare_digest(parts[0], self.api._token):
            self.send_error(404)
            return
        if len(parts) == 4 and parts[1] == "img":
            item = self.api._image(parts[2], parts[3])
            if item is None or item.data is None:
                self.send_error(404)
                return
            self._send(item.data, IMAGE_MIME.get(item.img_type or "", "application/octet-stream"),
                       cache=True)
        elif len(parts) == 2 and parts[1] in STATIC_FILES:
            path, mime = STATIC_FILES[parts[1]]
            self._send(path.read_bytes(), mime)
        else:
            self.send_error(404)

    def _send(self, body: bytes, mime: str, cache: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def _start_server(api: Api) -> ThreadingHTTPServer:
    handler = type("Handler", (_Handler,), {"api": api})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    if not webview2_installed():
        message_box("Webfänger", "Webfänger braucht die Microsoft Edge WebView2-Laufzeit. "
                                 "Sie ist in Windows 11 enthalten und lässt sich hier kostenlos "
                                 f"installieren:\n\n{WEBVIEW2_DOWNLOAD}")
        return
    # Die schlichte Oberfläche braucht keine Grafikbeschleunigung; ohne GPU-Prozess
    # belegt WebView2 rund 60 MB weniger Arbeitsspeicher.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")
    import webview

    api = Api()
    server = _start_server(api)
    url = f"http://127.0.0.1:{server.server_port}/{api._token}/index.html"
    window = webview.create_window("Webfänger", url=url, js_api=api, width=1100, height=800,
                                   min_size=(860, 640), background_color=BACKGROUND[api._dark],
                                   text_select=False)
    api._window = window
    window.events.shown += api._on_shown
    window.events.closing += api._on_closing
    try:
        webview.start(private_mode=True)
    finally:
        api._window = None
        server.shutdown()
