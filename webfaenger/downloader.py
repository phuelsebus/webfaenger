"""Bilder parallel herunterladen, filtern und speichern."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import DEFAULT_TYPES, DownloadReport, ImageCandidate, Progress
from .naming import NameContext, NamingOptions, build_stem, resolve_target
from .net import FetchError, fetch, type_from_mime, type_from_url


@dataclass
class DownloadOptions:
    folder: Path
    naming: NamingOptions = field(default_factory=NamingOptions)
    allowed_types: frozenset[str] = DEFAULT_TYPES
    min_kb: int = 10
    workers: int = 6
    timeout: float = 20


def prefilter(candidates: list[ImageCandidate],
              allowed_types: frozenset[str]) -> tuple[list[ImageCandidate], int]:
    """Entfernt Kandidaten, deren URL-Typ abgewählt ist. Unbekannte Typen bleiben
    und werden nach dem Download anhand des Content-Type geprüft."""
    kept = [c for c in candidates if c.type_hint is None or c.type_hint in allowed_types]
    return kept, len(candidates) - len(kept)


@dataclass
class _RunState:
    page_url: str
    next_index: int
    started: datetime = field(default_factory=datetime.now)
    seen_hashes: set[str] = field(default_factory=set)


class Downloader:
    """Lädt Kandidaten herunter. `cancel()` bricht ab, `on_progress` meldet den Stand.

    Netzwerkzugriffe laufen parallel; Auswertung, Benennung und Speichern passieren
    nacheinander im aufrufenden Thread, daher ist keine Sperre nötig."""

    def __init__(self, options: DownloadOptions,
                 on_progress: Callable[[Progress], None] | None = None):
        self.options = options
        self.on_progress = on_progress or (lambda p: None)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self, page_url: str, candidates: list[ImageCandidate]) -> DownloadReport:
        opts = self.options
        report = DownloadReport()
        todo, report.skipped_type = prefilter(candidates, opts.allowed_types)
        opts.folder.mkdir(parents=True, exist_ok=True)
        state = _RunState(page_url=page_url, next_index=opts.naming.start)

        def work(c: ImageCandidate):
            if self._cancel.is_set():
                return None, None, None
            try:
                data, final_url, ctype = fetch(c.url, referer=page_url, timeout=opts.timeout)
            except FetchError as exc:
                return None, None, str(exc)
            except Exception as exc:  # ein kaputtes Bild darf den Lauf nie beenden
                return None, None, f"Unerwarteter Fehler: {exc}"
            return data, type_from_mime(ctype) or type_from_url(final_url), None

        with ThreadPoolExecutor(max_workers=max(1, opts.workers)) as pool:
            futures = [pool.submit(work, c) for c in todo]
            # Ergebnisse in Seitenreihenfolge auswerten, damit die Nummerierung
            # der Reihenfolge auf der Webseite entspricht.
            for done, (c, future) in enumerate(zip(todo, futures), start=1):
                data, img_type, error = future.result()
                if self._cancel.is_set():
                    report.cancelled = True
                    pool.shutdown(wait=False, cancel_futures=True)
                    self._emit(done, len(todo), report, "Abgebrochen")
                    break
                msg = self._process(c, data, img_type, error, state, report)
                self._emit(done, len(todo), report, msg)
        return report

    def _process(self, c: ImageCandidate, data: bytes | None, img_type: str | None,
                 error: str | None, state: _RunState, report: DownloadReport) -> str:
        """Prüft ein geladenes Bild und speichert es; gibt die Log-Meldung zurück."""
        opts = self.options
        if error:
            report.failed.append((c.url, error))
            return f"Fehler: {error}"
        if img_type is None:
            report.skipped_type += 1
            return "Kein Bild – übersprungen"
        if img_type not in opts.allowed_types:
            report.skipped_type += 1
            return f"Typ {img_type} abgewählt – übersprungen"
        if len(data) < opts.min_kb * 1024:
            report.skipped_small += 1
            return "Zu klein – übersprungen"

        digest = hashlib.sha1(data).hexdigest()
        if digest in state.seen_hashes:
            report.skipped_duplicate += 1
            return "Doppelt – übersprungen"
        state.seen_hashes.add(digest)

        ctx = NameContext(c.url, state.page_url, state.next_index, digest, state.started)
        target = resolve_target(opts.folder, build_stem(opts.naming, ctx), img_type,
                                opts.naming.collision)
        if target is None:
            report.skipped_existing += 1
            return "Existiert bereits – übersprungen"
        try:
            _write_atomic(target, data)
        except OSError as exc:
            report.failed.append((c.url, f"Speichern fehlgeschlagen: {exc}"))
            return "Speichern fehlgeschlagen"
        state.next_index += 1
        report.saved.append(target)
        report.bytes_written += len(data)
        return f"Gespeichert: {target.name}"

    def _emit(self, done: int, total: int, report: DownloadReport, msg: str) -> None:
        self.on_progress(Progress(done, total, len(report.saved), report.bytes_written, msg))


def _write_atomic(target: Path, data: bytes) -> None:
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, target)
