import pytest

from webfaenger.net import to_ascii_url
from webfaenger.scraper import decode_html, extract_images, normalize_url, parse_srcset

PAGE = "https://example.com/blog/post.html"

HTML = """
<html><head>
  <meta property="og:image" content="/share.jpg">
  <link rel="icon" href="/favicon.ico">
</head><body>
  <img src="a.png">
  <img src="data:image/gif;base64,R0lGOD" data-src="/lazy/real.jpg">
  <img src="small.jpg" srcset="small.jpg 400w, big.jpg 1600w, mid.jpg 800w">
  <picture>
    <source type="image/webp" srcset="pic.webp 1x, pic@2x.webp 2x">
    <img src="pic.jpg">
  </picture>
  <a href="https://cdn.example.com/full/photo.JPEG">groß</a>
  <a href="/kontakt.html">Kontakt</a>
  <div style="background-image: url('bg.webp')"></div>
  <img src="a.png#fragment">
  <img src="javascript:void(0)">
  <img src="">
  <video><source type="video/mp4" srcset="clip.mp4"></video>
</body></html>
"""


def test_extract_images():
    urls = [c.url for c in extract_images(HTML, PAGE)]
    assert urls == [
        "https://example.com/share.jpg",
        "https://example.com/blog/a.png",
        "https://example.com/lazy/real.jpg",
        "https://example.com/blog/big.jpg",
        "https://example.com/blog/pic@2x.webp",
        "https://example.com/blog/pic.jpg",
        "https://cdn.example.com/full/photo.JPEG",
        "https://example.com/blog/bg.webp",
    ]


def test_type_hints():
    hints = {c.url.rsplit("/", 1)[1]: c.type_hint for c in extract_images(HTML, PAGE)}
    assert hints["photo.JPEG"] == "jpg"
    assert hints["bg.webp"] == "webp"


def test_base_href():
    html = '<base href="https://other.org/assets/"><img src="x.png">'
    assert extract_images(html, PAGE)[0].url == "https://other.org/assets/x.png"


def test_url_without_extension_is_kept():
    c = extract_images('<img src="/image?id=5">', PAGE)[0]
    assert c.type_hint is None


@pytest.mark.parametrize("value, expected", [
    ("a.jpg 1x, b.jpg 2x", "b.jpg"),
    ("a.jpg 100w,b.jpg 50w", "a.jpg"),
    ("only.jpg", "only.jpg"),
    ("https://x.org/i.jpg?a=1,2 300w, https://x.org/j.jpg 600w", "https://x.org/j.jpg"),
    ("", None),
])
def test_parse_srcset(value, expected):
    assert parse_srcset(value) == expected


def test_normalize_url():
    assert normalize_url(" example.com/x ") == "https://example.com/x"
    assert normalize_url("http://a.de") == "http://a.de"
    with pytest.raises(ValueError):
        normalize_url("")
    with pytest.raises(ValueError):
        normalize_url("ftp://example.com")


def test_decode_html_charset():
    data = '<meta charset="iso-8859-1"><p>Grüße</p>'.encode("latin-1")
    assert "Grüße" in decode_html(data, "text/html")
    assert "Grüße" in decode_html("Grüße".encode("utf-8"), "text/html; charset=UTF-8")


def test_to_ascii_url():
    assert (to_ascii_url("https://müller.de/Bild à.jpg?q=ä&x=1")
            == "https://xn--mller-kva.de/Bild%20%C3%A0.jpg?q=%C3%A4&x=1")
    assert to_ascii_url("https://a.org/x%20y.jpg") == "https://a.org/x%20y.jpg"
    assert to_ascii_url("http://127.0.0.1:8000/p") == "http://127.0.0.1:8000/p"
