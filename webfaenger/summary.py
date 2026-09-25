"""Texte für Übersicht und Abschlussbericht (von GUI und Kommandozeile genutzt)."""

from __future__ import annotations

from urllib.parse import urlsplit

from .downloader import prefilter
from .models import DownloadReport, ScanResult


def format_bytes(n: int) -> str:
    if n < 1024 * 1024:
        return f"{max(n, 0) / 1024:.0f} KB"
    return f"{n / 1_048_576:.1f} MB".replace(".", ",")


def scan_summary(result: ScanResult, allowed: frozenset[str]) -> tuple[str, str, str]:
    """(Überschrift, Typenzeile, Filterzeile) für die Ergebnisübersicht."""
    total = len(result.candidates)
    host = urlsplit(result.page_url).hostname or result.page_url
    if total == 0:
        return (f"Keine Bilder gefunden auf {host}",
                "Möglicherweise lädt die Webseite ihre Bilder erst per JavaScript nach. "
                "Das unterstützt Webfänger noch nicht.", "")
    headline = f"{total} {'Bild' if total == 1 else 'Bilder'} gefunden auf {host}"
    types = " · ".join(f"{t} {n}" for t, n in result.type_counts().most_common())
    kept, skipped = prefilter(result.candidates, allowed)
    if not kept:
        filt = ("Alle sind durch den Dateityp-Filter ausgeblendet. Unter „Einstellungen“ "
                "weitere Dateitypen anhaken.")
    elif skipped:
        filt = f"{skipped} durch den Dateityp-Filter ausgeblendet, {len(kept)} werden geprüft"
    else:
        filt = f"Alle {len(kept)} werden geprüft"
    return headline, types, filt


def report_summary(report: DownloadReport) -> str:
    saved = len(report.saved)
    head = "Abgebrochen" if report.cancelled else "Fertig"
    parts = [f"{head}: {saved} {'Bild' if saved == 1 else 'Bilder'} gespeichert "
             f"({format_bytes(report.bytes_written)})"]
    skipped = [(report.skipped_small, "zu klein"), (report.skipped_duplicate, "doppelt"),
               (report.skipped_type, "anderer Dateityp"),
               (report.skipped_existing, "schon vorhanden"),
               (len(report.failed), "mit Fehler")]
    details = ", ".join(f"{n} {label}" for n, label in skipped if n)
    if details:
        parts.append(f"Nicht gespeichert: {details}")
    return "\n".join(parts)
