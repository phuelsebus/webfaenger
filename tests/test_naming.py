from datetime import datetime

import pytest

from webfaenger.naming import (Collision, NameContext, NamingMode, NamingOptions,
                               build_stem, original_stem, resolve_target, sanitize,
                               validate_pattern)

CTX = NameContext("https://cdn.example.com/img/Sonne%20Bild.jpg?w=800",
                  "https://www.example.com/galerie", 7, "abcdef1234" * 4,
                  datetime(2026, 9, 25, 14, 30, 5))


@pytest.mark.parametrize("raw, expected", [
    ("normal", "normal"),
    ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
    ("  .versteckt. ", "versteckt"),
    ("CON", "_CON"),
    ("nul.tar", "_nul.tar"),
    ("", "bild"),
    ("...", "bild"),
    ("../../evil", "_.._evil"),  # keine Pfadtrenner mehr
])
def test_sanitize(raw, expected):
    assert sanitize(raw) == expected


def test_sanitize_truncates():
    assert len(sanitize("x" * 500)) == 120


def test_original_stem_decodes_and_drops_query():
    assert original_stem(CTX.url) == "Sonne Bild"


def test_modes():
    assert build_stem(NamingOptions(), CTX) == "Sonne Bild"
    assert build_stem(NamingOptions(mode=NamingMode.NUMBERED, prefix="urlaub"), CTX) == "urlaub_007"
    opts = NamingOptions(mode=NamingMode.PATTERN, pattern="{domain}_{datum}_{nr:03}_{hash}")
    assert build_stem(opts, CTX) == "www.example.com_2026-09-25_007_abcdef12"


def test_pattern_validation():
    assert validate_pattern("{name}_{nr:03}") is None
    assert validate_pattern("{foo}") == "{foo} ist kein bekannter Platzhalter."
    assert validate_pattern("{nr") == "Die geschweiften Klammern { } passen nicht zusammen."
    assert validate_pattern("  ") == "Das Muster ist leer."
    assert validate_pattern("{name.__class__}") is not None
    assert validate_pattern("{name") is not None


def test_pattern_cannot_escape_folder():
    opts = NamingOptions(mode=NamingMode.PATTERN, pattern="../../{name}")
    assert "/" not in build_stem(opts, CTX) and "\\" not in build_stem(opts, CTX)


def test_collisions(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a_1.jpg").write_bytes(b"x")
    assert resolve_target(tmp_path, "a", "jpg", Collision.RENAME).name == "a_2.jpg"
    assert resolve_target(tmp_path, "a", "jpg", Collision.OVERWRITE).name == "a.jpg"
    assert resolve_target(tmp_path, "a", "jpg", Collision.SKIP) is None
    assert resolve_target(tmp_path, "b", "jpg", Collision.SKIP).name == "b.jpg"
