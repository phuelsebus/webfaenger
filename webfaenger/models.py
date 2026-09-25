"""Gemeinsame Datenstrukturen."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Dateiendungen, die als Bild gelten (normalisiert, ohne Punkt).
IMAGE_TYPES = ("jpg", "png", "webp", "gif", "svg", "avif", "bmp", "ico", "tiff")

# Standardauswahl in der Oberfläche.
DEFAULT_TYPES = frozenset({"jpg", "png", "webp", "gif", "avif"})


@dataclass(frozen=True)
class ImageCandidate:
    """Eine auf der Seite gefundene Bild-URL."""

    url: str
    source: str  # img, srcset, meta, link, style
    type_hint: str | None  # aus der URL abgeleiteter Typ, None wenn unbekannt


@dataclass
class ScanResult:
    """Ergebnis der Seitenanalyse."""

    page_url: str
    candidates: list[ImageCandidate]

    def type_counts(self) -> Counter[str]:
        return Counter(c.type_hint or "unbekannt" for c in self.candidates)


@dataclass
class DownloadReport:
    """Zusammenfassung eines Downloads."""

    saved: list[Path] = field(default_factory=list)
    skipped_small: int = 0
    skipped_duplicate: int = 0
    skipped_type: int = 0
    skipped_existing: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (url, Fehler)
    bytes_written: int = 0
    cancelled: bool = False


@dataclass(frozen=True)
class Progress:
    """Fortschrittsmeldung an die Oberfläche."""

    done: int
    total: int
    saved: int
    bytes_written: int
    message: str
