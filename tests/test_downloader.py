"""Ende-zu-Ende-Test gegen einen lokalen HTTP-Server (kein Internet nötig)."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from webfaenger.downloader import Fetcher, save_images, select
from webfaenger.models import DEFAULT_TYPES
from webfaenger.naming import Collision, NamingMode, NamingOptions
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


def test_fetch_select_save(server, tmp_path):
    result = scan(server)
    assert len(result.candidates) == 7

    seen = []
    items = Fetcher(on_item=lambda item, done, total: seen.append((item.id, done, total))).run(
        result.page_url, result.candidates)
    status = {i.url.rsplit("/", 1)[1]: i.status for i in items}
    assert status == {"one.jpg": "ok", "two.png": "ok", "copy.jpg": "duplicate",
                      "tiny.jpg": "ok", "missing.jpg": "error", "noext": "ok",
                      "vector.svg": "ok"}
    assert [s[0] for s in seen] == list(range(7))  # Seitenreihenfolge
    assert next(i for i in items if i.status == "error").error.endswith("(404)")

    chosen = select(items, DEFAULT_TYPES, min_kb=10)
    assert chosen.skipped_small == 1 and chosen.skipped_type == 1  # tiny.jpg, svg

    progress = []
    report = save_images(chosen.chosen, page_url=result.page_url, folder=tmp_path,
                         naming=NamingOptions(mode=NamingMode.NUMBERED, prefix="bild"),
                         on_progress=lambda done, total, msg: progress.append(done))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bild_001.jpg", "bild_002.png",
                                                          "bild_003.webp"]
    assert report.bytes_written == sum(i.size for i in chosen.chosen)
    assert progress == [1, 2, 3]


def test_save_skips_existing(server, tmp_path):
    result = scan(server)
    items = select(Fetcher().run(result.page_url, result.candidates), DEFAULT_TYPES, 10).chosen
    naming = NamingOptions(collision=Collision.SKIP)
    save_images(items, page_url=result.page_url, folder=tmp_path, naming=naming)
    again = save_images(items, page_url=result.page_url, folder=tmp_path, naming=naming)
    assert again.skipped_existing == 3 and not again.saved


def test_cancel(server):
    result = scan(server)
    fetcher = Fetcher(workers=1)
    fetcher.cancel()
    items = fetcher.run(result.page_url, result.candidates)
    assert all(i.status == "cancelled" for i in items)


def test_memory_limit(server):
    result = scan(server)
    items = Fetcher(max_total_bytes=25_000).run(result.page_url, result.candidates)
    assert [i.status for i in items[:2]] == ["ok", "error"]
    assert "Speichergrenze" in items[1].error
