"""Helles und dunkles Design, passend zur Windows-Einstellung.

Tk kann keine abgerundeten Ecken zeichnen. Knöpfe, Eingabefelder, Karten und
Checkboxen sind deshalb kleine Bilder, die dieses Modul beim Start rendert,
ohne Bildbibliothek. Wechselt das Systemdesign, werden dieselben Bilder neu
befüllt, und die Oberfläche passt sich ohne Neustart an.
"""

from __future__ import annotations

import base64
import math
import struct
import sys
import zlib
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

LIGHT = {
    "bg": "#F3F4F6", "card": "#FFFFFF", "card_border": "#E5E7EB",
    "fg": "#111827", "muted": "#4B5563", "text_dis": "#9CA3AF",
    "field": "#FFFFFF", "field_dis": "#F3F4F6", "border": "#D1D5DB", "control": "#9CA3AF",
    "button": "#F3F4F6", "button_hover": "#E5E7EB", "button_press": "#D1D5DB",
    "button_dis": "#F9FAFB",
    "accent": "#2563EB", "accent_hover": "#1D4ED8", "accent_press": "#1E40AF",
    "on_accent": "#FFFFFF", "link": "#1D4ED8", "link_hover": "#1E3A8A",
    "error": "#DC2626", "inset": "#F9FAFB", "select": "#DBEAFE",
    "trough": "#E5E7EB", "thumb": "#D1D5DB", "thumb_hover": "#9CA3AF", "ring": "#111827",
}
DARK = {
    "bg": "#111113", "card": "#1B1B1F", "card_border": "#2B2B31",
    "fg": "#F4F4F5", "muted": "#A1A1AA", "text_dis": "#63636B",
    "field": "#141417", "field_dis": "#1B1B1F", "border": "#3A3A42", "control": "#71717A",
    "button": "#28282E", "button_hover": "#323239", "button_press": "#3C3C44",
    "button_dis": "#202025",
    "accent": "#2563EB", "accent_hover": "#1D4ED8", "accent_press": "#1E40AF",
    "on_accent": "#FFFFFF", "link": "#60A5FA", "link_hover": "#93C5FD",
    "error": "#F87171", "inset": "#141417", "select": "#1E3A8A",
    "trough": "#2B2B31", "thumb": "#3F3F46", "thumb_hover": "#5A5A63", "ring": "#F4F4F5",
}


_STRETCH = 96  # Breite der Bildmitte in Pixeln, siehe _Canvas.stretched


# ------------------------------------------------------------ Systemdesign

def system_prefers_dark() -> bool:
    """True, wenn Windows für Apps den dunklen Modus eingestellt hat."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def set_titlebar_dark(root: tk.Tk, dark: bool) -> None:
    """Färbt die Windows-Titelleiste passend ein (ab Windows 10 20H1)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE, ältere Kennung
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        # Rahmen neu zeichnen, sonst greift die Farbe erst beim nächsten Fokuswechsel.
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
    except (AttributeError, OSError):
        pass


# ------------------------------------------------------ Mini-Rasterizer

def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _rrect(x0, y0, x1, y1, r):
    """Vorzeichenbehafteter Abstand zu einem abgerundeten Rechteck."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = (x1 - x0) / 2 - r, (y1 - y0) / 2 - r

    def dist(x, y):
        qx, qy = abs(x - cx) - hw, abs(y - cy) - hh
        return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r
    return dist


def _circle(cx, cy, r):
    return lambda x, y: math.hypot(x - cx, y - cy) - r


def _stroke(points, width):
    segments = list(zip(points, points[1:]))

    def dist(x, y):
        best = math.inf
        for (ax, ay), (bx, by) in segments:
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
        return best - width / 2
    return dist


class _Canvas:
    """RGBA-Fläche mit Kantenglättung über Abstandsfunktionen."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.px = [[0.0, 0.0, 0.0, 0.0] for _ in range(w * h)]  # vormultipliziert

    def fill(self, dist, color: str) -> None:
        r, g, b = _rgb(color)
        for y in range(self.h):
            row = y * self.w
            for x in range(self.w):
                cover = 0.5 - dist(x + 0.5, y + 0.5)
                if cover <= 0:
                    continue
                a = 1.0 if cover >= 1 else cover
                p = self.px[row + x]
                keep = 1 - a
                p[0] = r * a + p[0] * keep
                p[1] = g * a + p[1] * keep
                p[2] = b * a + p[2] * keep
                p[3] = a + p[3] * keep

    def stretched(self, extra_w: int, extra_h: int) -> "_Canvas":
        """Vervielfältigt die mittlere Spalte/Zeile. Tk kachelt die Bildmitte
        beim Aufziehen; eine breite Mitte hält die Zahl der Kacheln klein."""
        mid_x, mid_y = self.w // 2, self.h // 2
        cols = list(range(mid_x)) + [mid_x] * (extra_w + 1) + list(range(mid_x + 1, self.w))
        rows = list(range(mid_y)) + [mid_y] * (extra_h + 1) + list(range(mid_y + 1, self.h))
        out = _Canvas(len(cols), len(rows))
        out.px = [self.px[y * self.w + x] for y in rows for x in cols]
        return out

    def png_base64(self) -> str:
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)
            for r, g, b, a in self.px[y * self.w:(y + 1) * self.w]:
                if a:
                    raw += bytes((round(r / a), round(g / a), round(b / a), round(a * 255)))
                else:
                    raw += b"\0\0\0\0"

        def chunk(kind: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + kind + data
                    + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))
        return base64.b64encode(png).decode("ascii")


# ------------------------------------------------------------------ Theme

class Theme:
    """Erzeugt das ttk-Theme "webfaenger" und schaltet zwischen Hell und Dunkel."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.style = ttk.Style(root)
        # 1.0 bei 100 % Windows-Skalierung, 1.5 bei 150 % usw.
        self.scale = max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
        self.images: dict[str, tk.PhotoImage] = {}
        self.dark: bool | None = None
        self.c = LIGHT
        self._setup_fonts()

    def px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    # -------------------------------------------------------------- Schrift

    def _setup_fonts(self) -> None:
        families = set(tkfont.families(self.root))
        variable = "Segoe UI Variable Text" in families
        text = "Segoe UI Variable Text" if variable else "Segoe UI"
        semibold = "Segoe UI Variable Text Semibold" if variable else "Segoe UI Semibold"
        display = "Segoe UI Variable Display" if "Segoe UI Variable Display" in families \
            else "Segoe UI"
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family=text, size=10)
        tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=9)
        self.font_body = (text, 10)
        self.font_small = (text, 9)
        self.font_label = (semibold, 9)
        self.font_semibold = (semibold, 10)
        self.font_headline = (semibold, 12)
        self.font_title = (display, 19, "bold")

    # ---------------------------------------------------------------- Bilder

    def _put(self, name: str, canvas: _Canvas) -> None:
        data = canvas.png_base64()
        if name in self.images:
            self.images[name].configure(data=data)
        else:
            self.images[name] = tk.PhotoImage(master=self.root, name=f"webf_{name}", data=data)

    def _box(self, name, radius, fill, border=None, border_width=1.0):
        slice_ = self.px(radius) + self.px(2)
        side = 2 * slice_ + 1
        canvas = _Canvas(side, side)
        r, bw = self.px(radius), self.px(border_width) if border_width >= 1 else border_width
        if border:
            canvas.fill(_rrect(0, 0, side, side, r), border)
            canvas.fill(_rrect(bw, bw, side - bw, side - bw, max(r - bw, 0)), fill)
        else:
            canvas.fill(_rrect(0, 0, side, side, r), fill)
        self._put(name, canvas.stretched(_STRETCH, _STRETCH))
        return slice_

    def _indicator(self, name, kind, fill, border, mark=None):
        """Checkbox (kind="check") oder Radio (kind="radio") mit Abstand zum Text."""
        box, gap = self.px(18), self.px(8)
        canvas = _Canvas(box + gap, box)
        if kind == "check":
            r = self.px(4)
            canvas.fill(_rrect(0, 0, box, box, r), border)
            inset = self.px(1.5) if border != fill else 0
            canvas.fill(_rrect(inset, inset, box - inset, box - inset, max(r - inset, 0)), fill)
            if mark:
                pts = [(box * 0.26, box * 0.52), (box * 0.43, box * 0.69), (box * 0.75, box * 0.34)]
                canvas.fill(_stroke(pts, self.px(2)), mark)
        else:
            half = box / 2
            canvas.fill(_circle(half, half, half), border)
            if border != fill:
                canvas.fill(_circle(half, half, half - self.px(1.5)), fill)
            if mark:
                canvas.fill(_circle(half, half, box * 0.19), mark)
        self._put(name, canvas)

    def _render_images(self) -> dict[str, object]:
        c = self.c
        slices = {}
        ring = 2
        slices["button"] = self._box("btn", 6, c["button"], c["border"])
        self._box("btn_hover", 6, c["button_hover"], c["border"])
        self._box("btn_press", 6, c["button_press"], c["border"])
        self._box("btn_dis", 6, c["button_dis"], c["card_border"])
        self._box("btn_focus", 6, c["button"], c["accent"], ring)
        self._box("acc", 6, c["accent"])
        self._box("acc_hover", 6, c["accent_hover"])
        self._box("acc_press", 6, c["accent_press"])
        self._box("acc_focus", 6, c["accent"], c["ring"], ring)
        slices["field"] = self._box("field", 6, c["field"], c["border"])
        self._box("field_focus", 6, c["field"], c["accent"], ring)
        self._box("field_dis", 6, c["field_dis"], c["card_border"])
        slices["card"] = self._box("card", 10, c["card"], c["card_border"])
        slices["inset"] = self._box("inset", 8, c["inset"], c["card_border"])

        for kind in ("check", "radio"):
            self._indicator(f"{kind}_off", kind, c["field"], c["control"])
            self._indicator(f"{kind}_off_hover", kind, c["field"], c["accent"])
            self._indicator(f"{kind}_on", kind, c["accent"], c["accent"], c["on_accent"])
            self._indicator(f"{kind}_on_hover", kind, c["accent_hover"], c["accent_hover"],
                            c["on_accent"])
            self._indicator(f"{kind}_dis", kind, c["field_dis"], c["card_border"])
            self._indicator(f"{kind}_dis_on", kind, c["button_press"], c["button_press"],
                            c["text_dis"])

        size = self.px(16)
        for name, color in (("chevron", c["muted"]), ("chevron_dis", c["text_dis"])):
            canvas = _Canvas(size + self.px(10), size)
            pts = [(size * 0.28, size * 0.40), (size * 0.5, size * 0.62), (size * 0.72, size * 0.40)]
            canvas.fill(_stroke(pts, self.px(1.6)), color)
            self._put(name, canvas)

        # Fortschrittsbalken und Scrollbalken als Pillen
        height = self.px(6)
        slices["pill"] = height // 2 + 1
        for name, color in (("pg_trough", c["trough"]), ("pg_bar", c["accent"])):
            canvas = _Canvas(height + 1, height)
            canvas.fill(_rrect(0, 0, height + 1, height, height / 2), color)
            self._put(name, canvas.stretched(_STRETCH, 0))
        width = self.px(8)
        slices["thumb"] = width // 2 + 1
        for name, color in (("sb_thumb", c["thumb"]), ("sb_thumb_hover", c["thumb_hover"])):
            canvas = _Canvas(width, width + 1)
            canvas.fill(_rrect(self.px(1), 0, width - self.px(1), width + 1,
                               (width - self.px(2)) / 2), color)
            self._put(name, canvas.stretched(0, _STRETCH))
        canvas = _Canvas(width, width)
        self._put("sb_trough", canvas)  # durchsichtig
        return slices

    # ------------------------------------------------------ Elemente/Layouts

    def _create_theme(self, slices) -> None:
        s = self.style
        img = lambda name: f"webf_{name}"  # noqa: E731

        def small(key):  # Wunschgröße: nur die Ecken, die Mitte wächst mit dem Inhalt
            return {"width": 2 * slices[key], "height": 2 * slices[key]}
        settings = {
            "Button.bg": {"element create": ("image", img("btn"),
                                             ("disabled", img("btn_dis")),
                                             ("pressed", img("btn_press")),
                                             ("active", img("btn_hover")),
                                             ("focus", img("btn_focus")),
                                             {"border": slices["button"], "sticky": "nsew", **small("button")})},
            "Accent.bg": {"element create": ("image", img("acc"),
                                             ("disabled", img("btn_dis")),
                                             ("pressed", img("acc_press")),
                                             ("active", img("acc_hover")),
                                             ("focus", img("acc_focus")),
                                             {"border": slices["button"], "sticky": "nsew", **small("button")})},
            "Field.bg": {"element create": ("image", img("field"),
                                            ("disabled", img("field_dis")),
                                            ("focus", img("field_focus")),
                                            {"border": slices["field"], "sticky": "nsew", **small("field")})},
            "Card.bg": {"element create": ("image", img("card"),
                                           {"border": slices["card"], "sticky": "nsew", **small("card")})},
            "Inset.bg": {"element create": ("image", img("inset"),
                                            {"border": slices["inset"], "sticky": "nsew", **small("inset")})},
            "Chevron.arrow": {"element create": ("image", img("chevron"),
                                                 ("disabled", img("chevron_dis")),
                                                 {"sticky": ""})},
            "Horizontal.Progressbar.trough": {"element create": (
                "image", img("pg_trough"),
                {"border": (slices["pill"], 0, slices["pill"], 0), "sticky": "ew",
                 "width": 2 * slices["pill"]})},
            "Horizontal.Progressbar.pbar": {"element create": (
                "image", img("pg_bar"),
                {"border": (slices["pill"], 0, slices["pill"], 0), "sticky": "nsew",
                 "width": 2 * slices["pill"]})},
            "Vertical.Scrollbar.trough": {"element create": ("image", img("sb_trough"),
                                                             {"sticky": "ns"})},
            "Vertical.Scrollbar.thumb": {"element create": (
                "image", img("sb_thumb"), ("pressed", img("sb_thumb_hover")),
                ("active", img("sb_thumb_hover")),
                {"border": (0, slices["thumb"], 0, slices["thumb"]), "sticky": "nsew",
                 "height": 2 * slices["thumb"]})},
        }
        for kind, element in (("check", "Check.indicator"), ("radio", "Radio.indicator")):
            settings[element] = {"element create": (
                "image", img(f"{kind}_off"),
                ("disabled", "selected", img(f"{kind}_dis_on")),
                ("disabled", img(f"{kind}_dis")),
                ("active", "selected", img(f"{kind}_on_hover")),
                ("selected", img(f"{kind}_on")),
                ("active", img(f"{kind}_off_hover")),
                {"sticky": ""})}

        def button(bg_element):
            return [("Button.background", {"sticky": "nswe", "children": [
                (bg_element, {"sticky": "nswe", "children": [
                    ("Button.padding", {"sticky": "nswe", "children": [
                        ("Button.label", {"sticky": "nswe"})]})]})]})]

        def check(indicator):
            return [("Checkbutton.background", {"sticky": "nswe", "children": [
                ("Checkbutton.padding", {"sticky": "nswe", "children": [
                    (indicator, {"side": "left", "sticky": ""}),
                    ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                        ("Checkbutton.label", {"sticky": "nswe"})]})]})]})]

        layouts = {
            "TButton": button("Button.bg"),
            "Accent.TButton": button("Accent.bg"),
            "Link.TButton": [("Button.background", {"sticky": "nswe", "children": [
                ("Button.focus", {"sticky": "nswe", "children": [
                    ("Button.padding", {"sticky": "nswe", "children": [
                        ("Button.label", {"sticky": "nswe"})]})]})]})],
            "TEntry": [("Entry.background", {"sticky": "nswe", "children": [
                ("Field.bg", {"sticky": "nswe", "children": [
                    ("Entry.padding", {"sticky": "nswe", "children": [
                        ("Entry.textarea", {"sticky": "nswe"})]})]})]})],
            "TCombobox": [("Combobox.background", {"sticky": "nswe", "children": [
                ("Field.bg", {"sticky": "nswe", "children": [
                    ("Chevron.arrow", {"side": "right", "sticky": ""}),
                    ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
                        ("Combobox.textarea", {"sticky": "nswe"})]})]})]})],
            "TCheckbutton": check("Check.indicator"),
            "TRadiobutton": check("Radio.indicator"),
            "Card.TFrame": [("Frame.background", {"sticky": "nswe", "children": [
                ("Card.bg", {"sticky": "nswe"})]})],
            "Inset.TFrame": [("Frame.background", {"sticky": "nswe", "children": [
                ("Inset.bg", {"sticky": "nswe"})]})],
            "Horizontal.TProgressbar": [("Horizontal.Progressbar.trough", {
                "sticky": "nswe", "children": [
                    ("Horizontal.Progressbar.pbar", {"side": "left", "sticky": "ns"})]})],
            "Vertical.TScrollbar": [("Vertical.Scrollbar.trough", {
                "sticky": "ns", "children": [
                    ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})],
        }
        for name, layout in layouts.items():
            settings.setdefault(name, {})["layout"] = layout
        s.theme_create("webfaenger", parent="clam", settings=settings)
        s.theme_use("webfaenger")

    def _configure_styles(self) -> None:
        c, s = self.c, self.style
        s.configure(".", background=c["card"], foreground=c["fg"], font=self.font_body,
                    bordercolor=c["border"], focuscolor=c["accent"], troughcolor=c["trough"],
                    selectbackground=c["select"], selectforeground=c["fg"],
                    insertcolor=c["fg"], fieldbackground=c["field"])
        s.map(".", foreground=[("disabled", c["text_dis"])])

        # Fensterhintergrund (außerhalb der Karten)
        s.configure("App.TFrame", background=c["bg"])
        for name in ("Title.TLabel", "Subtitle.TLabel", "Header.TLabel"):
            s.configure(name, background=c["bg"])
        s.configure("Title.TLabel", font=self.font_title)
        s.configure("Subtitle.TLabel", foreground=c["muted"])

        s.configure("Card.TFrame", background=c["bg"])  # Ecken außerhalb der Karte
        s.configure("Inset.TFrame", background=c["card"])
        s.configure("Muted.TLabel", foreground=c["muted"])
        s.configure("Small.TLabel", foreground=c["muted"], font=self.font_small)
        s.configure("Error.TLabel", foreground=c["error"])
        s.configure("Field.TLabel", font=self.font_label, foreground=c["muted"])
        s.configure("Section.TLabel", font=self.font_semibold)
        s.configure("Headline.TLabel", font=self.font_headline)

        s.configure("TButton", padding=(self.px(14), self.px(7)), anchor="center",
                    font=self.font_body)
        s.configure("Accent.TButton", foreground=c["on_accent"], font=self.font_semibold)
        s.map("Accent.TButton", foreground=[("disabled", c["text_dis"])])
        s.configure("Link.TButton", foreground=c["link"], font=self.font_semibold,
                    padding=(0, self.px(2)), focusthickness=1)
        s.map("Link.TButton", foreground=[("active", c["link_hover"])])

        s.configure("TEntry", padding=(self.px(9), self.px(6)))
        s.configure("TCombobox", padding=(self.px(9), self.px(6)),
                    selectbackground=c["field"], selectforeground=c["fg"])
        s.map("TCombobox", selectbackground=[("readonly", c["field"])],
              selectforeground=[("readonly", c["fg"])],
              fieldbackground=[("readonly", c["field"])])
        s.configure("TCheckbutton", padding=(0, self.px(3)))
        s.configure("TRadiobutton", padding=(0, self.px(3)))

    # --------------------------------------------------------------- Umschalten

    def apply(self, dark: bool) -> None:
        self.dark = dark
        self.c = DARK if dark else LIGHT
        slices = self._render_images()
        if "webfaenger" not in self.style.theme_names():
            self._create_theme(slices)
        self._configure_styles()
        c = self.c
        self.root.configure(bg=c["bg"])
        # Für Tk-Widgets ohne ttk-Style (Menüs, Listen der Auswahlfelder)
        for pattern, value in (("*Menu.background", c["card"]), ("*Menu.foreground", c["fg"]),
                               ("*Menu.activeBackground", c["select"]),
                               ("*Menu.activeForeground", c["fg"]),
                               ("*TCombobox*Listbox.background", c["card"]),
                               ("*TCombobox*Listbox.foreground", c["fg"]),
                               ("*TCombobox*Listbox.selectBackground", c["select"]),
                               ("*TCombobox*Listbox.selectForeground", c["fg"])):
            self.root.option_add(pattern, value)
        set_titlebar_dark(self.root, dark)
