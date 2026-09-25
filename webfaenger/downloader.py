"""Bilder parallel laden, prüfen und die ausgewählten speichern.

Der Ablauf hat zwei Schritte: `Fetcher` lädt alle gefundenen Bilder in den
Arbeitsspeicher, damit die Oberfläche eine Vorschau zeigen kann.
`save_images` schreibt danach nur die ausgewählten auf die Festplatte.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import DownloadReport, ImageCandidate
from .naming import NameContext, NamingOptions, build_stem, resolve_target
from .net import FetchError, fetch, type_from_mime, type_from_url

# Obergrenze für alle Bilder einer Suche im Speicher.
MAX_TOTAL_BYTES = 400 * 1024 * 1024


@dataclass
class FetchedImage:
    """Ein geladenes (oder gescheitertes) Bild einer Suche."""

    id: int
    url: str
    status: str = "pending"  # ok, duplicate, notimage, error, cancelled
    data: bytes | None = field(default=None, repr=False)
    img_type: str | None = None
    digest: str | None = None
    error: str | None = None

    @property
    def size(self) -> int:
        return len(self.data) if self.data else 0


class Fetcher:
    """Lädt Kandidaten parallel. `on_item` meldet jedes fertige Bild in Seitenreihenfolge."""

    def __init__(self, *, workers: int = 6, timeout: float = 20,
                 on_item: Callable[[FetchedImage, int, int], None] | None = None,
                 max_total_bytes: int = MAX_TOTAL_BYTES):
        self.workers = workers
        self.timeout = timeout
        self.on_item = on_item or (lambda item, done, total: None)
        self.max_total_bytes = max_total_bytes
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self, page_url: str, candidates: list[ImageCandidate]) -> list[FetchedImage]:
        items = [FetchedImage(i, c.url) for i, c in enumerate(candidates)]
        seen: set[str] = set()
        total_bytes = 0

        def work(item: FetchedImage):
            if self._cancel.is_set():
                return None
            try:
                data, final_url, ctype = fetch(item.url, referer=page_url, timeout=self.timeout)
            except FetchError as exc:
                return exc
            except Exception as exc:  # ein kaputtes Bild darf den Lauf nie beenden
                return FetchError(f"Unerwarteter Fehler: {exc}")
            return data, type_from_mime(ctype) or type_from_url(final_url)

        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as pool:
            futures = [pool.submit(work, item) for item in items]
            # In Seitenreihenfolge auswerten, damit Vorschau und Nummern der Seite folgen.
            for done, (item, future) in enumerate(zip(items, futures), start=1):
                result = future.result()
                if self._cancel.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    for rest in items[done - 1:]:
                        rest.status = "cancelled"
                    break
                if isinstance(result, FetchError):
                    item.status, item.error = "error", str(result)
                else:
                    data, img_type = result
                    digest = hashlib.sha1(data).hexdigest()
                    if img_type is None:
                        item.status = "notimage"
                    elif digest in seen:
                        item.status = "duplicate"
                    elif total_bytes + len(data) > self.max_total_bytes:
                        item.status, item.error = "error", "Speichergrenze der Vorschau erreicht"
                    else:
                        seen.add(digest)
                        total_bytes += len(data)
                        item.status, item.data = "ok", data
                        item.img_type, item.digest = img_type, digest
                self.on_item(item, done, len(items))
        return items


def prefilter(candidates: list[ImageCandidate],
              allowed_types: frozenset[str]) -> tuple[list[ImageCandidate], int]:
    """Entfernt Kandidaten, deren URL-Typ abgewählt ist. Unbekannte Typen bleiben
    und werden nach dem Laden anhand des Content-Type geprüft."""
    kept = [c for c in candidates if c.type_hint is None or c.type_hint in allowed_types]
    return kept, len(candidates) - len(kept)


@dataclass
class Selection:
    chosen: list[FetchedImage]
    skipped_type: int
    skipped_small: int


def select(items: Iterable[FetchedImage], allowed_types: frozenset[str],
           min_kb: int) -> Selection:
    """Wählt die geladenen Bilder aus, die zu Typ- und Größenfilter passen."""
    chosen, wrong_type, small = [], 0, 0
    for item in items:
        if item.status != "ok":
            continue
        if item.img_type not in allowed_types:
            wrong_type += 1
        elif item.size < min_kb * 1024:
            small += 1
        else:
            chosen.append(item)
    return Selection(chosen, wrong_type, small)


def save_images(items: list[FetchedImage], *, page_url: str, folder: Path,
                naming: NamingOptions,
                on_progress: Callable[[int, int, str], None] | None = None) -> DownloadReport:
    """Schreibt die Bilder in `folder`; die Nummerierung folgt der Reihenfolge von `items`."""
    report = DownloadReport()
    folder.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    index = naming.start
    for done, item in enumerate(items, start=1):
        ctx = NameContext(item.url, page_url, index, item.digest or "", started)
        stem = build_stem(naming, ctx)
        target = resolve_target(folder, stem, item.img_type, naming.collision)
        if target is None:
            report.skipped_existing += 1
            message = f"Übersprungen, Datei existiert schon: {stem}.{item.img_type}"
        else:
            try:
                _write_atomic(target, item.data)
            except OSError as exc:
                report.failed.append((item.url, f"Speichern fehlgeschlagen ({exc.strerror or exc})"))
                message = f"Fehler: {target.name} konnte nicht gespeichert werden"
            else:
                index += 1
                report.saved.append(target)
                report.bytes_written += item.size
                message = f"Gespeichert: {target.name}"
        if on_progress:
            on_progress(done, len(items), message)
    return report


def _write_atomic(target: Path, data: bytes) -> None:
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, target)
