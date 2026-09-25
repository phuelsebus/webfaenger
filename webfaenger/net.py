"""HTTP-Hilfen auf Basis der Standardbibliothek."""

from __future__ import annotations

import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .models import IMAGE_TYPES

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

_EXT_ALIASES = {"jpeg": "jpg", "jpe": "jpg", "jfif": "jpg", "tif": "tiff", "svgz": "svg"}

_MIME_TO_TYPE = {
    "image/jpeg": "jpg", "image/pjpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/gif": "gif", "image/svg+xml": "svg", "image/avif": "avif", "image/bmp": "bmp",
    "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico", "image/tiff": "tiff",
}

# Fehler, bei denen sich ein erneuter Versuch lohnt.
_RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """Verständliche Fehlermeldung für die Oberfläche."""


def type_from_url(url: str) -> str | None:
    """Bildtyp aus der Dateiendung der URL, z. B. "jpg"; None wenn keine Bildendung."""
    suffix = PurePosixPath(unquote(urlsplit(url).path)).suffix.lower().lstrip(".")
    suffix = _EXT_ALIASES.get(suffix, suffix)
    return suffix if suffix in IMAGE_TYPES else None


def to_ascii_url(url: str) -> str:
    """Kodiert Umlaute & Co. in Pfad/Query und internationale Domains (IDNA)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    netloc = host + (f":{parts.port}" if parts.port else "")
    safe = "/%:@!$&'()*+,;=~-._"
    return urlunsplit((parts.scheme, netloc, quote(parts.path, safe=safe),
                       quote(parts.query, safe=safe + "?"), ""))


def type_from_mime(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return _MIME_TO_TYPE.get(content_type.split(";")[0].strip().lower())


def fetch(url: str, *, referer: str | None = None, timeout: float = 15,
          max_bytes: int = 50 * 1024 * 1024, retries: int = 2,
          accept: str = "*/*") -> tuple[bytes, str, str | None]:
    """Lädt eine URL. Gibt (Inhalt, finale URL, Content-Type) zurück."""
    headers = {"User-Agent": USER_AGENT, "Accept": accept,
               "Accept-Language": "de,en;q=0.8"}
    if referer:
        headers["Referer"] = to_ascii_url(referer)
    request = urllib.request.Request(to_ascii_url(url), headers=headers)

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                length = resp.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > max_bytes:
                    raise FetchError(f"Datei zu groß ({int(length) // 1_048_576} MB)")
                data = resp.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise FetchError("Datei zu groß")
                return data, resp.geturl(), resp.headers.get("Content-Type")
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRY_STATUS and attempt < retries:
                time.sleep(_retry_delay(exc, attempt))
                continue
            raise FetchError(_http_message(exc.code)) from exc
        except urllib.error.URLError as exc:
            # Eine unbekannte Adresse oder ein Zertifikatsfehler ändert sich nicht
            # beim erneuten Versuch.
            permanent = isinstance(exc.reason, (socket.gaierror, ssl.SSLError))
            if attempt < retries and not permanent:
                time.sleep(1 + attempt)
                continue
            raise FetchError(_url_error_message(exc.reason)) from exc
        except (TimeoutError, ConnectionError) as exc:
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
            raise FetchError("Die Verbindung wurde unterbrochen oder hat zu lange gedauert.") from exc
        except (ValueError, http.client.HTTPException) as exc:
            raise FetchError("Die Antwort des Servers war fehlerhaft.") from exc
    raise FetchError("Unbekannter Fehler")  # pragma: no cover


def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), 10)
    return 1.5 * (attempt + 1)


def _url_error_message(reason: object) -> str:
    if isinstance(reason, socket.gaierror):
        return "Adresse nicht gefunden. Bitte URL und Internetverbindung prüfen."
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "Das Sicherheitszertifikat der Seite ist ungültig."
    if isinstance(reason, ssl.SSLError):
        return "Sichere Verbindung zur Seite fehlgeschlagen."
    if isinstance(reason, ConnectionRefusedError):
        return "Der Server lehnt die Verbindung ab."
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "Zeitüberschreitung: Die Seite antwortet nicht."
    return "Seite nicht erreichbar. Bitte URL und Internetverbindung prüfen."


def _http_message(code: int) -> str:
    return {
        401: "Nur mit Anmeldung erreichbar (401)",
        403: "Zugriff verweigert (403)",
        404: "Nicht gefunden (404)",
        410: "Nicht mehr vorhanden (410)",
        429: "Zu viele Anfragen, der Server bremst (429). Etwas warten und erneut versuchen.",
    }.get(code, f"Der Server meldet einen Fehler ({code}). Später erneut versuchen.")
