"""Einstellungen dauerhaft in %APPDATA%\\Webfaenger\\settings.json speichern."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .models import DEFAULT_TYPES


def _default_folder() -> str:
    pictures = Path.home() / "Pictures"
    return str((pictures if pictures.is_dir() else Path.home()) / "Webfänger")


@dataclass
class Settings:
    folder: str = field(default_factory=_default_folder)
    types: list[str] = field(default_factory=lambda: sorted(DEFAULT_TYPES))
    min_kb: int = 10
    naming_mode: str = "original"
    prefix: str = "bild"
    pattern: str = "{domain}_{nr:03}"
    collision: str = "rename"
    subfolder_per_site: bool = False
    show_options: bool = False


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Webfaenger" / "settings.json"


def load(path: Path | None = None) -> Settings:
    """Lädt die Einstellungen; bei fehlender oder kaputter Datei gelten die Standards."""
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    defaults = Settings()
    known = {}
    for f in fields(Settings):
        value = data.get(f.name, getattr(defaults, f.name))
        # Falscher Typ in der Datei (z. B. von Hand bearbeitet) -> Standardwert.
        if not isinstance(value, type(getattr(defaults, f.name))):
            value = getattr(defaults, f.name)
        known[f.name] = value
    return Settings(**known)


def save(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass  # Einstellungen sind Komfort; ein Fehler darf die App nicht stören
