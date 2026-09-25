"""Ende-zu-Ende-Test gegen einen lokalen HTTP-Server (kein Internet nötig)."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from webfaenger.downloader import Downloader, DownloadOptions
from webfaenger.models import DEFAULT_TYPES
from webfaenger.naming import NamingMode, NamingOptions
from webfaenger.scraper import scan

BIG = b"\xff\xd8" + b"J" * 20_000       # "JPEG", 20 KB
BIG2 = b"\x89PNG" + b"P" * 20_000       # "PNG", 20 KB
TINY = b"\xff\xd8" + b"t" * 100          # zu klein

PAGE = b"""<html><body>
<img src="/one.jpg"><img src="/two.png"><img src="/copy.jpg">
<img src="/tiny.jpg"><img src="/missing.jpg"><img src="/noext">
<img src="/vector.svg"><a href="/page.html">x</a>
</body></html>"""

ROUTES = {
    "/": ("text/html; charset=utf-8", PAGE),
    "/one.jpg": ("image/jpeg", BIG),
    "/two.png": ("image/png", BIG2),
    "/copy.jpg": ("image/jpeg", BIG),           # gleicher Inhalt wie one.jpg
    "/tiny.jpg": ("image/jpeg", TINY),
    "/noext": ("image/webp", b"RIFF" + b"W" * 20_000),
    "/vector.svg": ("image/svg+xml", b"<svg/>" * 5000),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = ROUTES.get(self.path)
        if not route:
            self.send_error(404)
            return
        ctype, body = route
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()


def test_end_to_end(server, tmp_path):
    result = scan(server)
    assert len(result.candidates) == 7

    options = DownloadOptions(folder=tmp_path, min_kb=10, allowed_types=DEFAULT_TYPES,
                              naming=NamingOptions(mode=NamingMode.NUMBERED, prefix="bild"))
    events = []
    report = Downloader(options, on_progress=events.append).run(result.page_url,
                                                                 result.candidates)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["bild_001.jpg", "bild_002.png",
                                                          "bild_003.webp"]
    assert report.skipped_duplicate == 1
    assert report.skipped_small == 1
    assert report.skipped_type == 1          # svg ist standardmäßig abgewählt
    assert len(report.failed) == 1 and "404" in report.failed[0][1]
    assert events[-1].done == events[-1].total == 6


def test_cancel(server, tmp_path):
    result = scan(server)
    downloader = Downloader(DownloadOptions(folder=tmp_path, workers=1))
    downloader.cancel()
    report = downloader.run(result.page_url, result.candidates)
    assert report.cancelled and not report.saved
