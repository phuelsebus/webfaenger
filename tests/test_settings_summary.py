import json

from webfaenger import settings
from webfaenger.models import DownloadReport, ImageCandidate, ScanResult
from webfaenger.summary import format_bytes, report_summary, scan_summary


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "s.json"
    s = settings.Settings(folder="D:/Bilder", types=["png"], min_kb=0, naming_mode="numbered")
    settings.save(s, path)
    assert settings.load(path) == s


def test_settings_tolerates_broken_file(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{kaputt", encoding="utf-8")
    assert settings.load(path) == settings.Settings()
    path.write_text(json.dumps({"min_kb": "zehn", "prefix": "x", "unbekannt": 1}), "utf-8")
    loaded = settings.load(path)
    assert loaded.min_kb == 10 and loaded.prefix == "x"


def test_format_bytes():
    assert format_bytes(2048) == "2 KB"
    assert format_bytes(4_404_019) == "4,2 MB"


def test_scan_summary():
    result = ScanResult("https://example.com/x", [
        ImageCandidate("https://example.com/a.jpg", "img", "jpg"),
        ImageCandidate("https://example.com/b.jpg", "img", "jpg"),
        ImageCandidate("https://example.com/c.svg", "img", "svg"),
        ImageCandidate("https://example.com/d", "img", None),
    ])
    headline, types, filt = scan_summary(result, frozenset({"jpg"}))
    assert headline == "4 Bilder gefunden auf example.com"
    assert types == "jpg 2 · svg 1 · unbekannt 1"
    assert filt == "1 durch den Dateityp-Filter ausgeblendet, 3 werden geprüft"
    only_jpg = ScanResult("https://example.com/", result.candidates[:2])
    assert scan_summary(only_jpg, frozenset({"png"}))[2].startswith("Alle sind durch")
    assert scan_summary(ScanResult("https://e.org/", []), frozenset())[0].startswith("Keine")


def test_report_summary():
    report = DownloadReport(bytes_written=3 * 1024, skipped_small=2,
                            failed=[("u", "404")])
    assert report_summary(report) == ("Fertig: 0 Bilder gespeichert (3 KB)\n"
                                      "Nicht gespeichert: 2 zu klein, 1 mit Fehler")
