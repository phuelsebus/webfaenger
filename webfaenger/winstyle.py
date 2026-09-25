"""Windows-Anbindung: Hell/Dunkel-Einstellung, Titelleiste, WebView2-Prüfung."""

from __future__ import annotations

import sys

WEBVIEW2_DOWNLOAD = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
_WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


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


def set_titlebar_dark(hwnd: int, dark: bool) -> None:
    """Färbt die Titelleiste eines Fensters passend ein (ab Windows 10 20H1)."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE, ältere Kennung
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        # Rahmen neu zeichnen, sonst greift die Farbe erst beim nächsten Fokuswechsel.
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
    except (AttributeError, OSError):
        pass


def webview2_installed() -> bool:
    """Prüft, ob die Edge-WebView2-Laufzeit vorhanden ist (in Windows 11 eingebaut)."""
    if sys.platform != "win32":
        return True
    import winreg
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{_WEBVIEW2_CLIENT}"),
                       (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{_WEBVIEW2_CLIENT}"),
                       (winreg.HKEY_CURRENT_USER, rf"Software\{_WEBVIEW2_CLIENT}")):
        try:
            with winreg.OpenKey(hive, path) as key:
                version = winreg.QueryValueEx(key, "pv")[0]
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def message_box(title: str, text: str) -> None:
    """Einfaches Windows-Meldungsfenster, auch wenn die Oberfläche nicht startet."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x30)  # MB_ICONWARNING
    except (AttributeError, OSError):
        print(f"{title}: {text}", file=sys.stderr)
