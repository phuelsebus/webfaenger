"""Einstieg: ohne Argumente startet die Oberfläche, mit URL die Kommandozeile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .downloader import Downloader, DownloadOptions, prefilter
from .models import DEFAULT_TYPES, IMAGE_TYPES
from .naming import Collision, NamingMode, NamingOptions, validate_pattern
from .net import FetchError
from .scraper import scan
from .summary import report_summary, scan_summary


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .gui import main as gui_main
        gui_main()
        return 0

    for stream in (sys.stdout, sys.stderr):  # umgeleitete Ausgabe nutzt sonst cp1252
        if stream:  # in der .exe ohne Konsole gibt es keine Streams
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="webfaenger",
                                description="Bilder einer Webseite herunterladen.")
    p.add_argument("url")
    p.add_argument("-o", "--ordner", type=Path, default=Path.cwd() / "Webfänger")
    p.add_argument("--typen", default=",".join(sorted(DEFAULT_TYPES)),
                   help=f"Komma-Liste aus: {', '.join(IMAGE_TYPES)}")
    p.add_argument("--min-kb", type=int, default=10)
    p.add_argument("--namen", choices=[m.value for m in NamingMode], default="original")
    p.add_argument("--praefix", default="bild")
    p.add_argument("--muster", default="{domain}_{nr:03}")
    p.add_argument("--kollision", choices=[c.value for c in Collision], default="rename")
    p.add_argument("--nur-suchen", action="store_true", help="nur Übersicht, kein Download")
    args = p.parse_args(argv)

    if args.namen == "pattern" and (err := validate_pattern(args.muster)):
        p.error(err)
    types = frozenset(t.strip().lower() for t in args.typen.split(",") if t.strip())

    try:
        result = scan(args.url)
    except (ValueError, FetchError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    for line in scan_summary(result, types):
        if line:
            print(line)
    kept, _ = prefilter(result.candidates, types)
    if args.nur_suchen or not kept:
        return 0

    options = DownloadOptions(
        folder=args.ordner, allowed_types=types, min_kb=args.min_kb,
        naming=NamingOptions(mode=NamingMode(args.namen), prefix=args.praefix,
                             pattern=args.muster, collision=Collision(args.kollision)))
    downloader = Downloader(options, on_progress=lambda pr: print(
        f"  [{pr.done}/{pr.total}] {pr.message}"))
    try:
        report = downloader.run(result.page_url, result.candidates)
    except KeyboardInterrupt:
        downloader.cancel()
        return 130

    print("\n" + report_summary(report))
    print(f"Ordner: {args.ordner.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
