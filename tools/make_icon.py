"""Zeichnet das App-Icon ohne Bildbibliothek und schreibt webfaenger/assets/icon.ico.

Motiv: dunkelblaue Kachel mit einem Bild (Berge und Sonne) und einem grünen
Download-Pfeil. Jede Größe wird einzeln mit 4x4-Supersampling gerendert.

Aufruf: python tools/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "webfaenger" / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)
SS = 4  # Supersampling pro Achse


def rgba(hex_color: str) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255


def rounded_rect(x0, y0, x1, y1, r):
    def inside(x, y):
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        cx = min(max(x, x0 + r), x1 - r)
        cy = min(max(y, y0 + r), y1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    return inside


def circle(cx, cy, r):
    return lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def polygon(*pts):
    def inside(x, y):
        hit = False
        j = len(pts) - 1
        for i, (xi, yi) in enumerate(pts):
            xj, yj = pts[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                hit = not hit
            j = i
        return hit
    return inside


def clip(shape, area):
    return lambda x, y: area(x, y) and shape(x, y)


# Koordinaten normiert auf 0..1, Reihenfolge = Zeichenreihenfolge.
photo = rounded_rect(0.25, 0.29, 0.75, 0.67, 0.03)
LAYERS = [
    (rounded_rect(0.03, 0.03, 0.97, 0.97, 0.21), rgba("#1E3A5F")),   # Kachel
    (rounded_rect(0.19, 0.23, 0.81, 0.73, 0.07), rgba("#FFFFFF")),   # Bilderrahmen
    (photo, rgba("#DBEAFE")),                                         # Himmel
    (clip(circle(0.62, 0.41, 0.055), photo), rgba("#F59E0B")),       # Sonne
    (clip(polygon((0.25, 0.67), (0.42, 0.44), (0.58, 0.67)), photo), rgba("#1E3A5F")),
    (clip(polygon((0.45, 0.67), (0.60, 0.51), (0.75, 0.67)), photo), rgba("#2B4C77")),
    (circle(0.73, 0.73, 0.2), rgba("#FFFFFF")),                      # Rand des Abzeichens
    (circle(0.73, 0.73, 0.165), rgba("#047857")),                    # grünes Abzeichen
    (rounded_rect(0.705, 0.62, 0.755, 0.76, 0.012), rgba("#FFFFFF")),  # Pfeilschaft
    (polygon((0.64, 0.72), (0.82, 0.72), (0.73, 0.83)), rgba("#FFFFFF")),  # Pfeilspitze
]


def render(size: int) -> bytes:
    """RGBA-Pixel, Zeile für Zeile."""
    out = bytearray()
    step = 1 / (size * SS)
    for py in range(size):
        for px in range(size):
            r = g = b = a = 0
            for sy in range(SS):
                y = (py * SS + sy + 0.5) * step
                for sx in range(SS):
                    x = (px * SS + sx + 0.5) * step
                    color = None
                    for inside, c in reversed(LAYERS):
                        if inside(x, y):
                            color = c
                            break
                    if color:
                        r += color[0]
                        g += color[1]
                        b += color[2]
                        a += 255
            n = SS * SS
            if a:
                # Farbe aus deckenden Samples mitteln, Alpha aus dem Anteil.
                cover = a // 255
                out += bytes((r // cover, g // cover, b // cover, a // n))
            else:
                out += b"\0\0\0\0"
    return bytes(out)


def png(size: int, pixels: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    stride = size * 4
    raw = b"".join(b"\0" + pixels[y * stride:(y + 1) * stride] for y in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    images = []
    for size in SIZES:
        data = png(size, render(size))
        images.append((size, data))
        if size == 256:
            (OUT / "icon.png").write_bytes(data)
    (OUT / "icon.ico").write_bytes(ico(images))
    print(f"geschrieben: {OUT / 'icon.ico'}")


if __name__ == "__main__":
    main()
