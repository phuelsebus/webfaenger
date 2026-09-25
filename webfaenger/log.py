"""Fehlerprotokoll in %LOCALAPPDATA%\\Webfaenger\\webfaenger.log.

Die .exe hat kein Konsolenfenster. Ohne Protokoll würde ein unerwarteter Fehler
spurlos verschwinden; so bleibt er für Rückfragen nachvollziehbar.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__

logger = logging.getLogger("webfaenger")


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Webfaenger"


def setup(on_crash=None) -> None:
    """Richtet das Protokoll ein. `on_crash(text)` wird bei unbehandelten Fehlern gerufen."""
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir() / "webfaenger.log", maxBytes=512_000,
                                      backupCount=1, encoding="utf-8")
    except OSError:
        return  # ohne Schreibrechte läuft die App trotzdem
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("Start Webfänger %s, Python %s", __version__, sys.version.split()[0])

    def crash(exc_type, exc, tb) -> None:
        logger.critical("Unbehandelter Fehler", exc_info=(exc_type, exc, tb))
        if on_crash:
            on_crash(f"{exc_type.__name__}: {exc}")

    sys.excepthook = crash
    threading.excepthook = lambda args: crash(args.exc_type, args.exc_value, args.exc_traceback)
