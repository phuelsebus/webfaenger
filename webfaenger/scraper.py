"""Webseite laden und Bild-URLs aus dem HTML extrahieren."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .models import ImageCandidate, ScanResult
from .net import FetchError, fetch, type_from_url

_LAZY_SRC = ("data-src", "data-lazy-src", "data-original", "data-lazy", "data-url",
             "data-full", "data-hi-res-src")
_LAZY_SRCSET = ("data-srcset", "data-lazy-srcset")
_META_KEYS = {"og:image", "og:image:url", "og:image:secure_url", "twitter:image",
              "twitter:image:src"}
_CSS_URL = re.compile(r"""url\(\s*(['"]?)(.+?)\1\s*\)""", re.IGNORECASE)
_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([\w-]+)""", re.IGNORECASE)


def normalize_url(raw: str) -> str:
    """Ergänzt fehlendes Schema und prüft die Eingabe."""
    url = raw.strip()
    if not url:
        raise ValueError("Bitte eine URL eingeben.")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Ungültige URL: {raw.strip()}")
    return url


def parse_srcset(value: str) -> str | None:
    """Wählt aus einem srcset die größte Variante (nach w- bzw. x-Angabe)."""
    best, best_score = None, -1.0
    for url, descriptor in _iter_srcset(value):
        score = 1.0
        d = descriptor.strip().lower()
        if d[-1:] in ("w", "x"):
            try:
                score = float(d[:-1])
            except ValueError:
                pass
        if score > best_score:
            best, best_score = url, score
    return best


def _iter_srcset(value: str):
    """Zerlegt srcset nach WHATWG-Regeln (vereinfacht): URL, dann Deskriptor bis Komma."""
    i, n = 0, len(value)
    while i < n:
        while i < n and (value[i].isspace() or value[i] == ","):
            i += 1
        start = i
        while i < n and not value[i].isspace():
            i += 1
        url = value[start:i]
        descriptor = ""
        if url.endswith(","):
            url = url.rstrip(",")
        else:
            start = i
            while i < n and value[i] != ",":
                i += 1
            descriptor = value[start:i]
        if url:
            yield url, descriptor


class _ImageExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.found: list[tuple[str, str]] = []  # (roh-URL, Quelle)
        self._base_seen = False

    def _add(self, raw: str | None, source: str) -> None:
        if raw and raw.strip():
            self.found.append((raw.strip(), source))

    def handle_starttag(self, tag, attrs):
        a = {k: v for k, v in attrs if v is not None}

        if tag == "base" and a.get("href") and not self._base_seen:
            self.base_url = urljoin(self.base_url, a["href"])
            self._base_seen = True
        elif tag == "img":
            self._handle_img(a)
        elif tag == "source":
            # <picture><source srcset>; Video-Quellen ignorieren
            if not a.get("type", "image/").startswith("video"):
                key = next((k for k in (*_LAZY_SRCSET, "srcset") if k in a), None)
                if key:
                    self._add(parse_srcset(a[key]), "srcset")
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in _META_KEYS:
                self._add(a.get("content"), "meta")
        elif tag == "link" and a.get("rel", "").lower() == "image_src":
            self._add(a.get("href"), "link")
        elif tag == "a" and a.get("href") and type_from_url(a["href"]):
            self._add(a["href"], "link")

        style = a.get("style")
        if style and "url(" in style:
            for match in _CSS_URL.finditer(style):
                self._add(match.group(2), "style")

    def _handle_img(self, a: dict[str, str]) -> None:
        # Pro <img> nur eine Quelle: die hochwertigste echte, nicht den Lazy-Platzhalter.
        options = [parse_srcset(a[k]) for k in (*_LAZY_SRCSET, "srcset") if k in a]
        options += [a[k] for k in (*_LAZY_SRC, "src") if k in a]
        for url in options:
            if url and url.strip() and not url.strip().startswith("data:"):
                self._add(url, "img")
                return


def extract_images(html: str, page_url: str) -> list[ImageCandidate]:
    """Findet alle Bild-URLs im HTML, absolut und ohne Duplikate (Reihenfolge bleibt)."""
    parser = _ImageExtractor(page_url)
    parser.feed(html)
    parser.close()

    seen: set[str] = set()
    result: list[ImageCandidate] = []
    for raw, source in parser.found:
        if raw.startswith(("data:", "javascript:", "#", "about:", "blob:")):
            continue
        parts = urlsplit(urljoin(parser.base_url, raw))
        if parts.scheme not in ("http", "https"):
            continue
        url = urlunsplit(parts._replace(fragment=""))
        if url in seen:
            continue
        seen.add(url)
        result.append(ImageCandidate(url=url, source=source, type_hint=type_from_url(url)))
    return result


def decode_html(data: bytes, content_type: str | None) -> str:
    charset = None
    if content_type and "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=")[1].split(";")[0].strip(' "\'')
    if not charset:
        match = _CHARSET.search(data[:4096])
        charset = match.group(1).decode("ascii") if match else "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def scan(raw_url: str, timeout: float = 15) -> ScanResult:
    """Lädt die Seite und liefert alle gefundenen Bilder."""
    url = normalize_url(raw_url)
    data, final_url, content_type = fetch(
        url, timeout=timeout, max_bytes=15 * 1024 * 1024,
        accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
    if content_type and not any(t in content_type.lower() for t in ("html", "xml")):
        if content_type.lower().startswith("image/"):
            # Direktlink auf ein Bild: das Bild selbst ist das Ergebnis.
            return ScanResult(final_url, [ImageCandidate(final_url, "direkt",
                                                         type_from_url(final_url))])
        raise FetchError("Die Adresse liefert keine Webseite.")
    return ScanResult(final_url, extract_images(decode_html(data, content_type), final_url))
