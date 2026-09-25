"""Tkinter-Oberfläche.

Die Oberfläche läuft im Hauptthread. Suche und Download laufen in Hintergrund-
threads und melden sich über eine Queue, die alle 100 ms abgefragt wird. So
bleibt das Fenster bedienbar und Tkinter wird nur aus dem Hauptthread benutzt.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from urllib.parse import urlsplit

from . import settings as settings_mod
from .downloader import Downloader, DownloadOptions, prefilter
from .models import IMAGE_TYPES, DownloadReport, Progress, ScanResult
from .naming import (Collision, NameContext, NamingMode, NamingOptions, build_stem,
                     sanitize, validate_pattern)
from .net import FetchError
from .scraper import normalize_url, scan
from .summary import format_bytes, report_summary, scan_summary

COLORS = {
    "bg": "#F8FAFC", "card": "#FFFFFF", "fg": "#0F172A", "muted": "#475569",
    "border": "#E4E7EB", "button": "#EEF2F6", "button_hover": "#E2E8F0",
    "primary": "#1E3A5F", "primary_hover": "#2B4C77",
    "accent": "#047857", "accent_hover": "#065F46",
    "disabled": "#94A3B8", "error": "#B91C1C", "focus": "#2563EB",
}

COLLISION_LABELS = {
    Collision.RENAME: "Neuen Namen vergeben (bild_1.jpg)",
    Collision.OVERWRITE: "Vorhandene Datei überschreiben",
    Collision.SKIP: "Bild überspringen",
}

PLACEHOLDER_HELP = ("Platzhalter: {name} Originalname · {nr} Nummer ({nr:03} = 001) · "
                    "{domain} Webseite · {datum} Datum · {zeit} Uhrzeit · {hash} Kurzkennung")


def _setup_fonts_and_style(root: tk.Tk) -> None:
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tkfont.nametofont(name).configure(family="Segoe UI", size=10)
    tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=9)

    c = COLORS
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=c["bg"])

    style.configure(".", background=c["bg"], foreground=c["fg"], bordercolor=c["border"],
                    focuscolor=c["focus"], font=("Segoe UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 16))
    style.configure("Subtitle.TLabel", foreground=c["muted"])

    style.configure("Card.TFrame", background=c["card"], relief="solid", borderwidth=1)
    style.configure("Inner.TFrame", background=c["card"])
    for widget in ("TLabel", "TCheckbutton", "TRadiobutton"):
        style.configure(f"Card.{widget}", background=c["card"])
        style.map(f"Card.{widget}", background=[("active", c["card"])])
    style.configure("Section.Card.TLabel", font=("Segoe UI Semibold", 11))
    style.configure("Headline.Card.TLabel", font=("Segoe UI Semibold", 12))
    style.configure("Muted.Card.TLabel", foreground=c["muted"])
    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(widget, indicatorsize=15, indicatormargin=(0, 0, 6, 0))
    style.configure("Error.Card.TLabel", foreground=c["error"])

    style.configure("TButton", padding=(12, 6), background=c["button"])
    style.map("TButton", background=[("disabled", c["bg"]), ("active", c["button_hover"])],
              foreground=[("disabled", c["disabled"])])
    for name, base, hover in (("Primary", c["primary"], c["primary_hover"]),
                              ("Accent", c["accent"], c["accent_hover"])):
        style.configure(f"{name}.TButton", background=base, foreground="#FFFFFF",
                        bordercolor=base, lightcolor=base, darkcolor=base,
                        font=("Segoe UI Semibold", 10))
        style.map(f"{name}.TButton",
                  background=[("disabled", c["disabled"]), ("active", hover)],
                  lightcolor=[("disabled", c["disabled"]), ("active", hover)],
                  darkcolor=[("disabled", c["disabled"]), ("active", hover)],
                  foreground=[("disabled", "#F8FAFC")])
    style.configure("Link.TButton", background=c["card"], foreground=c["primary"],
                    borderwidth=0, padding=(0, 2), font=("Segoe UI Semibold", 10))
    style.map("Link.TButton", background=[("active", c["card"])],
              foreground=[("active", c["primary_hover"])])

    style.configure("TEntry", fieldbackground="#FFFFFF", padding=5)
    style.map("TEntry", bordercolor=[("focus", c["focus"])], lightcolor=[("focus", c["focus"])])
    style.configure("TSpinbox", fieldbackground="#FFFFFF", padding=4, arrowsize=12)
    style.configure("TCombobox", fieldbackground="#FFFFFF", padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")],
              selectbackground=[("readonly", "#FFFFFF")],
              selectforeground=[("readonly", c["fg"])])
    style.configure("Horizontal.TProgressbar", background=c["accent"], troughcolor=c["button"],
                    bordercolor=c["border"], lightcolor=c["accent"], darkcolor=c["accent"])


def _install_entry_menu(root: tk.Tk) -> None:
    """Rechtsklick-Menü und Strg+A für alle Eingabefelder (bietet Tk nicht von selbst)."""
    menu = tk.Menu(root, tearoff=False)
    target: dict[str, tk.Widget] = {}

    def select_all(widget) -> str:
        widget.select_range(0, "end")
        widget.icursor("end")
        return "break"

    for label, event in (("Ausschneiden", "<<Cut>>"), ("Kopieren", "<<Copy>>"),
                         ("Einfügen", "<<Paste>>")):
        menu.add_command(label=label, command=lambda e=event: target["w"].event_generate(e))
    menu.add_separator()
    menu.add_command(label="Alles markieren", command=lambda: select_all(target["w"]))

    def popup(event) -> None:
        target["w"] = event.widget
        event.widget.focus_set()
        menu.tk_popup(event.x_root, event.y_root)

    for cls in ("TEntry", "TSpinbox"):
        root.bind_class(cls, "<Button-3>", popup, add="+")
        root.bind_class(cls, "<Control-a>", lambda e: select_all(e.widget))


def _icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "icon.ico"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = settings_mod.load()
        self.queue: queue.Queue = queue.Queue()
        self.scan_result: ScanResult | None = None
        self.downloader: Downloader | None = None
        self.last_folder: Path | None = None
        self._scan_id = 0
        self._state = "idle"

        s = self.settings
        self.url = tk.StringVar()
        self.folder = tk.StringVar(value=s.folder)
        self.subfolder = tk.BooleanVar(value=s.subfolder_per_site)
        self.type_vars = {t: tk.BooleanVar(value=t in s.types) for t in IMAGE_TYPES}
        self.min_kb = tk.StringVar(value=str(s.min_kb))
        self.naming_mode = tk.StringVar(value=s.naming_mode)
        self.prefix = tk.StringVar(value=s.prefix)
        self.pattern = tk.StringVar(value=s.pattern)
        collision = Collision(s.collision) if s.collision in Collision._value2member_map_ \
            else Collision.RENAME
        self.collision = tk.StringVar(value=COLLISION_LABELS[collision])

        root.title("Webfänger")
        if _icon_path().is_file():
            root.iconbitmap(default=str(_icon_path()))
        _setup_fonts_and_style(root)
        _install_entry_menu(root)
        self._build()

        self.url.trace_add("write", lambda *_: self._on_url_changed())
        for var in (*self.type_vars.values(), self.min_kb):
            var.trace_add("write", lambda *_: self._refresh_summary())
        for var in (self.naming_mode, self.prefix, self.pattern):
            var.trace_add("write", lambda *_: self._refresh_naming())
        root.bind("<Escape>", lambda e: self._cancel())
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._refresh_naming()
        self._set_state("idle")
        # Breite fest an den Startzustand binden; lange Texte brechen um statt
        # das Fenster aufzuziehen. Die Höhe folgt weiter dem Inhalt.
        root.update_idletasks()
        width = max(root.winfo_reqwidth(), 680)
        root.minsize(width, 0)
        root.maxsize(width, root.winfo_screenheight())
        for label in (self.headline, self.types_line, self.filter_line, self.status):
            label.configure(wraplength=width - 100)
        self.url_entry.focus_set()
        root.after(100, self._poll)

    # ------------------------------------------------------------------ Aufbau

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Webfänger", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Bilder von einer Webseite in einen Ordner herunterladen",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(0, 12))

        self._build_source(self._card(outer))
        self._build_options(self._card(outer))
        self._build_result(self._card(outer))

    def _card(self, parent) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill="x", pady=(0, 12))
        card.columnconfigure(1, weight=1)
        return card

    def _build_source(self, card: ttk.Frame) -> None:
        ttk.Label(card, text="Webseite (URL)", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12))
        self.url_entry = ttk.Entry(card, textvariable=self.url)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self._start_scan())
        self.search_btn = ttk.Button(card, text="Bilder suchen", command=self._start_scan,
                                     width=16)
        self.search_btn.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self.url_error = ttk.Label(card, text="", style="Error.Card.TLabel")
        self.url_error.grid(row=1, column=1, columnspan=2, sticky="w", pady=(2, 6))

        ttk.Label(card, text="Zielordner", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12))
        self.folder_entry = ttk.Entry(card, textvariable=self.folder)
        self.folder_entry.grid(row=2, column=1, sticky="ew")
        self.browse_btn = ttk.Button(card, text="Durchsuchen…", command=self._browse, width=16)
        self.browse_btn.grid(row=2, column=2, sticky="ew", padx=(8, 0))
        self.subfolder_chk = ttk.Checkbutton(
            card, text="Für jede Webseite einen eigenen Unterordner anlegen",
            variable=self.subfolder, style="Card.TCheckbutton")
        self.subfolder_chk.grid(row=3, column=1, columnspan=2, sticky="w", pady=(6, 0))

    def _build_options(self, card: ttk.Frame) -> None:
        self.options_btn = ttk.Button(card, style="Link.TButton", command=self._toggle_options)
        self.options_btn.grid(row=0, column=0, columnspan=2, sticky="w")
        self.naming_hint = ttk.Label(card, text="", style="Muted.Card.TLabel")
        self.naming_hint.grid(row=0, column=2, sticky="e")

        body = self.options_body = ttk.Frame(card, style="Inner.TFrame")
        body.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        body.columnconfigure(1, weight=1)
        pad = {"padx": (0, 12), "pady": (0, 10), "sticky": "nw"}

        ttk.Label(body, text="Dateitypen", style="Card.TLabel").grid(row=0, column=0, **pad)
        types = ttk.Frame(body, style="Inner.TFrame")
        types.grid(row=0, column=1, sticky="w", pady=(0, 10))
        for i, t in enumerate(IMAGE_TYPES):
            ttk.Checkbutton(types, text=t.upper(), variable=self.type_vars[t],
                            style="Card.TCheckbutton", width=6).grid(
                row=i // 5, column=i % 5, sticky="w")

        ttk.Label(body, text="Mindestgröße", style="Card.TLabel").grid(row=1, column=0, **pad)
        size = ttk.Frame(body, style="Inner.TFrame")
        size.grid(row=1, column=1, sticky="w", pady=(0, 10))
        ttk.Spinbox(size, from_=0, to=100_000, increment=5, width=7,
                    textvariable=self.min_kb).pack(side="left")
        ttk.Label(size, text="KB  (kleinere Bilder wie Icons werden übersprungen)",
                  style="Muted.Card.TLabel").pack(side="left", padx=(8, 0))

        ttk.Label(body, text="Dateinamen", style="Card.TLabel").grid(row=2, column=0, **pad)
        naming = ttk.Frame(body, style="Inner.TFrame")
        naming.grid(row=2, column=1, sticky="ew", pady=(0, 10))
        naming.columnconfigure(1, weight=1)
        modes = ttk.Frame(naming, style="Inner.TFrame")
        modes.grid(row=0, column=0, columnspan=2, sticky="w")
        for value, label in ((NamingMode.ORIGINAL, "Originalname"),
                             (NamingMode.NUMBERED, "Nummeriert"),
                             (NamingMode.PATTERN, "Eigenes Muster")):
            ttk.Radiobutton(modes, text=label, value=value.value, variable=self.naming_mode,
                            style="Card.TRadiobutton").pack(side="left", padx=(0, 16))

        self.prefix_row = ttk.Frame(naming, style="Inner.TFrame")
        ttk.Label(self.prefix_row, text="Präfix", style="Card.TLabel").pack(side="left")
        ttk.Entry(self.prefix_row, textvariable=self.prefix, width=24).pack(
            side="left", padx=(8, 0))
        self.pattern_row = ttk.Frame(naming, style="Inner.TFrame")
        self.pattern_row.columnconfigure(1, weight=1)
        ttk.Label(self.pattern_row, text="Muster", style="Card.TLabel").grid(row=0, column=0)
        ttk.Entry(self.pattern_row, textvariable=self.pattern).grid(
            row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(self.pattern_row, text=PLACEHOLDER_HELP, style="Muted.Card.TLabel",
                  wraplength=440).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.naming_preview = ttk.Label(naming, text="", style="Muted.Card.TLabel")
        self.naming_preview.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Label(body, text="Wenn die Datei\nschon existiert", style="Card.TLabel").grid(
            row=3, column=0, **pad)
        ttk.Combobox(body, textvariable=self.collision, state="readonly", width=34,
                     values=list(COLLISION_LABELS.values())).grid(row=3, column=1, sticky="w")

        self._show_options(self.settings.show_options)

    def _build_result(self, card: ttk.Frame) -> None:
        card.columnconfigure(0, weight=1)
        self.headline = ttk.Label(card, text="Noch keine Seite durchsucht",
                                  style="Headline.Card.TLabel")
        self.headline.grid(row=0, column=0, columnspan=4, sticky="w")
        self.types_line = ttk.Label(
            card, text="URL oben einfügen und auf „Bilder suchen“ klicken.",
            style="Muted.Card.TLabel")
        self.types_line.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))
        self.filter_line = ttk.Label(card, text="", style="Muted.Card.TLabel")
        self.filter_line.grid(row=2, column=0, columnspan=4, sticky="w")

        self.progress = ttk.Progressbar(card, mode="determinate")
        self.progress.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(12, 4))
        self.status = ttk.Label(card, text="", style="Muted.Card.TLabel")
        self.status.grid(row=4, column=0, sticky="w")

        buttons = ttk.Frame(card, style="Inner.TFrame")
        buttons.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        self.download_btn = ttk.Button(buttons, text="Herunterladen", command=self._start_download)
        self.download_btn.pack(side="left")
        self.cancel_btn = ttk.Button(buttons, text="Abbrechen", command=self._cancel)
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.open_btn = ttk.Button(buttons, text="Ordner öffnen", command=self._open_folder)
        self.open_btn.pack(side="right")

        self.log_btn = ttk.Button(card, text="▸ Details anzeigen", style="Link.TButton",
                                  command=self._toggle_log)
        self.log_btn.grid(row=6, column=0, sticky="w", pady=(10, 0))
        self.log_frame = ttk.Frame(card, style="Inner.TFrame")
        self.log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(self.log_frame, height=8, wrap="none", font="TkFixedFont",
                           relief="solid", borderwidth=1, state="disabled",
                           background=COLORS["bg"], foreground=COLORS["fg"])
        scroll = ttk.Scrollbar(self.log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")

    # ---------------------------------------------------------- Ein-/Ausklappen

    def _show_options(self, show: bool) -> None:
        self.settings.show_options = show
        # Der Namens-Hinweis in der Kopfzeile ist nur eingeklappt nötig; ausgeklappt
        # steht das Beispiel direkt bei den Namensoptionen.
        if show:
            self.options_body.grid()
            self.naming_hint.grid_remove()
            self.options_btn.configure(text="▾ Einstellungen ausblenden")
        else:
            self.options_body.grid_remove()
            self.naming_hint.grid()
            self.options_btn.configure(text="▸ Einstellungen anzeigen")

    def _toggle_options(self) -> None:
        self._show_options(not self.settings.show_options)

    def _toggle_log(self) -> None:
        if self.log_frame.winfo_ismapped():
            self.log_frame.grid_remove()
            self.log_btn.configure(text="▸ Details anzeigen")
        else:
            self.log_frame.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(6, 0))
            self.log_btn.configure(text="▾ Details ausblenden")

    # ------------------------------------------------------------------ Zustand

    def _set_state(self, state: str) -> None:
        """idle → scanning → scanned → downloading → done."""
        self._state = state
        busy = state in ("scanning", "downloading")
        can_download = state in ("scanned", "done") and self.scan_result is not None and bool(
            prefilter(self.scan_result.candidates, self._allowed_types())[0])

        self.search_btn.configure(
            state="disabled" if busy else "normal",
            text="Suche läuft…" if state == "scanning" else "Bilder suchen",
            style="TButton" if can_download else "Primary.TButton")
        self.download_btn.configure(state="normal" if can_download else "disabled",
                                    style="Accent.TButton" if can_download else "TButton")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        self.open_btn.configure(state="normal" if self.last_folder else "disabled")
        for widget in (self.url_entry, self.folder_entry, self.browse_btn, self.subfolder_chk):
            widget.configure(state="disabled" if state == "downloading" else "normal")

        if state == "scanning":
            self.progress.configure(mode="indeterminate", value=0)
            self.progress.start(12)
        elif str(self.progress.cget("mode")) == "indeterminate":
            self.progress.stop()  # setzt den Wert auf 0, daher nur nach der Suche
            self.progress.configure(mode="determinate")

    # ------------------------------------------------------------ Einstellungen

    def _allowed_types(self) -> frozenset[str]:
        return frozenset(t for t, var in self.type_vars.items() if var.get())

    def _min_kb(self) -> int | None:
        try:
            value = int(self.min_kb.get())
        except ValueError:
            return None
        return value if value >= 0 else None

    def _collision(self) -> Collision:
        for key, label in COLLISION_LABELS.items():
            if label == self.collision.get():
                return key
        return Collision.RENAME

    def _naming_options(self) -> NamingOptions:
        return NamingOptions(mode=NamingMode(self.naming_mode.get()),
                             prefix=self.prefix.get().strip(), pattern=self.pattern.get(),
                             collision=self._collision())

    def _refresh_naming(self) -> None:
        mode = self.naming_mode.get()
        if mode == NamingMode.NUMBERED:
            self.prefix_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        else:
            self.prefix_row.grid_remove()
        if mode == NamingMode.PATTERN:
            self.pattern_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        else:
            self.pattern_row.grid_remove()

        if mode == NamingMode.PATTERN and (error := validate_pattern(self.pattern.get())):
            self.naming_preview.configure(text=f"Muster ungültig: {error}",
                                          style="Error.Card.TLabel")
            self.naming_hint.configure(text="")
            return

        sample = self.scan_result.candidates[0] if self.scan_result and \
            self.scan_result.candidates else None
        ctx = NameContext(
            url=sample.url if sample else "https://example.com/bilder/sonnenuntergang.jpg",
            page_url=self.scan_result.page_url if self.scan_result else "https://example.com/",
            index=1, digest="3f2a9c1be07d" + "0" * 28, when=datetime.now())
        name = f"{build_stem(self._naming_options(), ctx)}.{(sample and sample.type_hint) or 'jpg'}"
        self.naming_preview.configure(text=f"Beispiel: {name}", style="Muted.Card.TLabel",
                                      wraplength=440)
        short = name if len(name) <= 36 else f"{name[:33]}…"
        self.naming_hint.configure(text=f"Dateinamen z. B. {short}")

    def _refresh_summary(self) -> None:
        if not self.scan_result or self._state in ("scanning", "downloading"):
            return
        headline, types, filt = scan_summary(self.scan_result, self._allowed_types())
        self.headline.configure(text=headline)
        self.types_line.configure(text=types)
        self.filter_line.configure(text=filt)
        self._set_state(self._state)  # Download-Knopf folgt dem Filter

    def _collect_settings(self) -> None:
        s = self.settings
        s.folder = self.folder.get().strip()
        s.types = sorted(self._allowed_types())
        s.min_kb = self._min_kb() if self._min_kb() is not None else s.min_kb
        s.naming_mode = self.naming_mode.get()
        s.prefix = self.prefix.get()
        s.pattern = self.pattern.get()
        s.collision = self._collision().value
        s.subfolder_per_site = self.subfolder.get()

    # ----------------------------------------------------------------- Aktionen

    def _on_url_changed(self) -> None:
        self.url_error.configure(text="")
        if self._state in ("scanned", "done"):
            self.scan_result = None
            self.headline.configure(text="Noch keine Seite durchsucht")
            self.types_line.configure(text="URL oben einfügen und auf „Bilder suchen“ klicken.")
            self.filter_line.configure(text="")
            self.status.configure(text="")
            self.progress.configure(value=0)
            self._set_state("idle")
            self._refresh_naming()

    def _browse(self) -> None:
        initial = self.folder.get() if Path(self.folder.get()).is_dir() else str(Path.home())
        chosen = filedialog.askdirectory(parent=self.root, initialdir=initial,
                                         title="Zielordner wählen", mustexist=False)
        if chosen:
            self.folder.set(str(Path(chosen)))

    def _start_scan(self) -> None:
        if self._state in ("scanning", "downloading"):
            return
        try:
            url = normalize_url(self.url.get())
        except ValueError as exc:
            self.url_error.configure(text=str(exc))
            self.url_entry.focus_set()
            return

        self._scan_id += 1
        scan_id = self._scan_id
        self.scan_result = None
        self.headline.configure(text="Webseite wird durchsucht…")
        self.types_line.configure(text=url)
        self.filter_line.configure(text="")
        self.status.configure(text="")
        self._log(f"Suche Bilder auf {url}")
        self._set_state("scanning")

        def work():
            try:
                result, error = scan(url), None
            except (ValueError, FetchError) as exc:
                result, error = None, str(exc)
            except Exception as exc:  # nie mit hängender Oberfläche enden
                result, error = None, f"Unerwarteter Fehler: {exc}"
            self.queue.put(("scan_done", (scan_id, result, error)))

        threading.Thread(target=work, daemon=True).start()

    def _start_download(self) -> None:
        if not self.scan_result or self._state in ("scanning", "downloading"):
            return
        folder_text = self.folder.get().strip()
        allowed = self._allowed_types()
        min_kb = self._min_kb()
        problem, in_options = None, True
        if not folder_text:
            problem, in_options = ("Kein Zielordner angegeben. Bitte über „Durchsuchen…“ "
                                   "einen Ordner wählen."), False
        elif not allowed:
            problem = "Kein Dateityp ausgewählt. Bitte mindestens einen Dateityp anhaken."
        elif min_kb is None:
            problem = "Die Mindestgröße muss eine ganze Zahl sein, z. B. 10."
        elif self.naming_mode.get() == NamingMode.PATTERN and (
                error := validate_pattern(self.pattern.get())):
            problem = f"Das Namensmuster funktioniert so nicht: {error}"
        if problem:
            if in_options:
                self._show_options(True)
            messagebox.showwarning("Bitte prüfen", problem, parent=self.root)
            return

        folder = Path(folder_text).expanduser()
        if self.subfolder.get():
            folder /= sanitize(urlsplit(self.scan_result.page_url).hostname or "seite")
        self.last_folder = folder
        self._collect_settings()
        settings_mod.save(self.settings)

        options = DownloadOptions(folder=folder, naming=self._naming_options(),
                                  allowed_types=allowed, min_kb=min_kb)
        self.downloader = Downloader(options, on_progress=lambda p: self.queue.put(("progress", p)))
        result = self.scan_result
        self.progress.configure(value=0, maximum=max(1, len(result.candidates)))
        self.status.configure(text="Download startet…")
        self._log(f"Speichere nach {folder}")
        self._set_state("downloading")

        def work():
            try:
                self.queue.put(("download_done", self.downloader.run(result.page_url,
                                                                      result.candidates)))
            except OSError:
                self.queue.put(("download_failed", "Der Zielordner lässt sich nicht anlegen. "
                                                   "Bitte einen anderen Ordner wählen."))
            except Exception as exc:
                self.queue.put(("download_failed", f"Unerwarteter Fehler: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _cancel(self) -> None:
        if self._state == "scanning":
            self._scan_id += 1  # Ergebnis der laufenden Suche wird ignoriert
            self.headline.configure(text="Suche abgebrochen")
            self._set_state("idle")
        elif self._state == "downloading" and self.downloader:
            self.downloader.cancel()
            self.cancel_btn.configure(state="disabled")
            self.status.configure(text="Wird abgebrochen…")

    def _open_folder(self) -> None:
        if self.last_folder and self.last_folder.is_dir():
            os.startfile(self.last_folder)  # noqa: S606 – öffnet den Explorer
        else:
            messagebox.showinfo("Ordner öffnen", "Den Ordner gibt es noch nicht. Er wird beim "
                                "ersten Download angelegt.", parent=self.root)

    def _on_close(self) -> None:
        if self._state == "downloading":
            if not messagebox.askyesno("Download läuft", "Download abbrechen und Webfänger "
                                       "schließen?\n\nBereits gespeicherte Bilder bleiben "
                                       "erhalten.", icon="warning", parent=self.root):
                return
            if self.downloader:
                self.downloader.cancel()
        self._collect_settings()
        settings_mod.save(self.settings)
        self.root.destroy()

    # --------------------------------------------------------- Rückmeldungen

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                getattr(self, f"_on_{kind}")(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _on_scan_done(self, payload) -> None:
        scan_id, result, error = payload
        if scan_id != self._scan_id:
            return
        if error:
            self.headline.configure(text="Webseite konnte nicht geladen werden")
            self.types_line.configure(text=error)
            self._log(f"Fehler: {error}")
            self._set_state("idle")
            return
        self.scan_result = result
        self._log(f"{len(result.candidates)} Bild-Adressen gefunden")
        self._set_state("scanned")
        self._refresh_summary()
        self._refresh_naming()
        if result.candidates:
            self.download_btn.focus_set()

    def _on_progress(self, p: Progress) -> None:
        self.progress.configure(maximum=max(1, p.total), value=p.done)
        self.status.configure(text=f"{p.done} von {p.total} geprüft · {p.saved} gespeichert · "
                                   f"{format_bytes(p.bytes_written)}")
        self._log(f"[{p.done}/{p.total}] {p.message}")

    def _on_download_done(self, report: DownloadReport) -> None:
        text = report_summary(report)
        if report.failed:
            text += "\nWas schiefging, steht unter „Details anzeigen“."
        self.status.configure(text=text)
        for url, error in report.failed:
            self._log(f"Fehlgeschlagen: {url} ({error})")
        self._set_state("done")
        if report.saved:
            self.open_btn.focus_set()

    def _on_download_failed(self, error: str) -> None:
        self.status.configure(text=f"Download nicht möglich. {error}")
        self._log(f"Fehler: {error}")
        self._set_state("scanned")

    def _log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def _enable_dpi_awareness() -> None:
    """Scharfe Darstellung auf skalierten Windows-Bildschirmen."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main() -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()
