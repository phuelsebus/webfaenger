"""Dateinamen für heruntergeladene Bilder erzeugen und absichern."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

# Windows-reservierte Gerätenamen (auch mit Endung verboten, z. B. "con.jpg").
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_STEM = 120  # hält den Gesamtpfad deutlich unter 260 Zeichen

PLACEHOLDERS = ("name", "nr", "domain", "datum", "zeit", "hash")


class NamingMode(str, Enum):
    ORIGINAL = "original"
    NUMBERED = "numbered"
    PATTERN = "pattern"


class Collision(str, Enum):
    RENAME = "rename"        # name_1.jpg, name_2.jpg, …
    OVERWRITE = "overwrite"
    SKIP = "skip"


@dataclass
class NamingOptions:
    mode: NamingMode = NamingMode.ORIGINAL
    prefix: str = "bild"
    pattern: str = "{domain}_{nr:03}"
    start: int = 1
    collision: Collision = Collision.RENAME


@dataclass(frozen=True)
class NameContext:
    url: str
    page_url: str
    index: int  # fortlaufende Nummer, beginnt bei options.start
    digest: str  # SHA-1 des Inhalts (hex)
    when: datetime


def sanitize(stem: str, fallback: str = "bild") -> str:
    """Macht einen Dateinamen (ohne Endung) unter Windows sicher."""
    stem = _INVALID_CHARS.sub("_", stem)
    stem = stem.strip(" .")  # Windows entfernt führende/abschließende Punkte/Leerzeichen
    stem = re.sub(r"_{2,}", "_", stem)[:_MAX_STEM].rstrip(" .")
    if not stem:
        return fallback
    if stem.split(".")[0].upper() in _RESERVED:
        stem = f"_{stem}"
    return stem


def original_stem(url: str) -> str:
    """Dateiname ohne Endung aus der URL, z. B. ".../Sonne%20Bild.jpg?x=1" -> "Sonne Bild"."""
    name = PurePosixPath(unquote(urlsplit(url).path)).name
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem


class _SafeFormatter(string.Formatter):
    """Erlaubt nur einfache Platzhalter – kein Attribut- oder Indexzugriff."""

    def get_field(self, field_name, args, kwargs):
        if not field_name.isidentifier():
            raise ValueError(f"Ungültiger Platzhalter: {{{field_name}}}")
        if field_name not in kwargs:
            raise ValueError(f"Unbekannter Platzhalter: {{{field_name}}}")
        return kwargs[field_name], field_name


_formatter = _SafeFormatter()


def validate_pattern(pattern: str) -> str | None:
    """Gibt eine Fehlermeldung zurück oder None, wenn das Muster gültig ist."""
    sample = NameContext("https://example.com/foto.jpg", "https://example.com/",
                         1, "0" * 40, datetime(2026, 1, 1))
    try:
        _render_pattern(pattern, sample)
    except (ValueError, IndexError, KeyError) as exc:
        return str(exc) or "Ungültiges Muster"
    return None


def _render_pattern(pattern: str, ctx: NameContext) -> str:
    return _formatter.format(
        pattern,
        name=original_stem(ctx.url) or "bild",
        nr=ctx.index,
        domain=urlsplit(ctx.page_url).hostname or "seite",
        datum=ctx.when.strftime("%Y-%m-%d"),
        zeit=ctx.when.strftime("%H-%M-%S"),
        hash=ctx.digest[:8],
    )


def build_stem(options: NamingOptions, ctx: NameContext) -> str:
    """Erzeugt den bereinigten Dateinamen ohne Endung."""
    if options.mode is NamingMode.NUMBERED:
        raw = f"{options.prefix}_{ctx.index:03}" if options.prefix else f"{ctx.index:03}"
    elif options.mode is NamingMode.PATTERN:
        raw = _render_pattern(options.pattern, ctx)
    else:
        raw = original_stem(ctx.url)
    return sanitize(raw)


def resolve_target(folder: Path, stem: str, ext: str, policy: Collision) -> Path | None:
    """Wählt den Zielpfad gemäß Kollisionsregel; None bedeutet überspringen."""
    target = folder / f"{stem}.{ext}"
    if not target.exists() or policy is Collision.OVERWRITE:
        return target
    if policy is Collision.SKIP:
        return None
    n = 1
    while True:
        target = folder / f"{stem}_{n}.{ext}"
        if not target.exists():
            return target
        n += 1
