"""Erzeugt das App-Icon: ein Spinnennetz, das ein Foto an seinem Faden heranzieht.

Das Motiv ist als SVG beschrieben. Microsoft Edge (headless) rechnet es in
jeder Icon-Größe direkt in Pixel um, damit die Linien auch bei 16 px scharf
bleiben. Bis 32 px gilt eine vereinfachte Variante mit weniger, dickeren Fäden.

Aufruf: python tools/make_icon.py [--preview vorschau.png]
Schreibt webfaenger/assets/icon.ico und icon.png (256 px).
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import math
import re
import struct
import subprocess
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "webfaenger" / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

CENTER = (76.0, 76.0)  # Mitte des Netzes


def _point(angle: float, radius: float) -> tuple[float, float]:
    a = math.radians(angle)
    return CENTER[0] + radius * math.cos(a), CENTER[1] + radius * math.sin(a)


def _web(spokes: int, rings: list[float], spoke_width: float, ring_width: float) -> str:
    """Speichen und leicht nach innen durchhängende Ringe, wie bei einem echten Netz."""
    angles = [i * 360 / spokes + 8 for i in range(spokes)]
    parts = []
    for a in angles:
        x, y = _point(a, 260)
        parts.append(f'<line x1="{CENTER[0]}" y1="{CENTER[1]}" x2="{x:.1f}" y2="{y:.1f}" '
                     f'stroke-width="{spoke_width}"/>')
    for r in rings:
        x0, y0 = _point(angles[0], r)
        d = [f"M{x0:.1f},{y0:.1f}"]
        for a, b in zip(angles, angles[1:] + angles[:1]):
            mid = (a + b) / 2 + (180 if b < a else 0)
            cx, cy = _point(mid, r * 0.8)
            x, y = _point(b, r)
            d.append(f"Q{cx:.1f},{cy:.1f} {x:.1f},{y:.1f}")
        parts.append(f'<path d="{" ".join(d)}" fill="none" stroke-width="{ring_width}"/>')
    return "\n".join(parts)


def _rotate(x: float, y: float, deg: float, ox: float, oy: float) -> tuple[float, float]:
    a = math.radians(deg)
    dx, dy = x - ox, y - oy
    return ox + dx * math.cos(a) - dy * math.sin(a), oy + dx * math.sin(a) + dy * math.cos(a)


def svg(small: bool) -> str:
    if small:
        web = _web(6, [46, 92], 10, 9)
        card, tilt, thread_w, knot = (96, 104, 140, 114), -9, 10, 9
    else:
        web = _web(8, [26, 52, 80, 110], 3.2, 2.8)
        card, tilt, thread_w, knot = (104, 112, 124, 100), -10, 4, 5
    x, y, w, h = card
    ox, oy = x + w / 2, y + h / 2
    inset = 10 if small else 10
    ix, iy, iw, ih = x + inset, y + inset, w - 2 * inset, h - 2 * inset
    # Der Faden hängt an der oberen linken Ecke der Karte.
    ax, ay = _rotate(x + 12, y + 6, tilt, ox, oy)
    # Bewegungsstriche unter der Karte: sie wird entlang des Fadens zum Netz gezogen.
    trail = ""
    if not small:
        length = math.hypot(ax - CENTER[0], ay - CENTER[1])
        dx, dy = (ax - CENTER[0]) / length, (ay - CENTER[1]) / length
        lines = []
        for fraction, size in ((0.3, 12), (0.5, 18), (0.7, 12)):
            sx, sy = _rotate(x + w * fraction, y + h, tilt, ox, oy)
            sx, sy = sx + dx * 9, sy + dy * 9
            lines.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{sx + dx * size:.1f}" '
                         f'y2="{sy + dy * size:.1f}"/>')
        trail = ('<g clip-path="url(#tile)" stroke="#FFFFFF" stroke-opacity="0.55" '
                 f'stroke-width="4" stroke-linecap="round">{"".join(lines)}</g>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#3B82F6"/><stop offset="1" stop-color="#1E3A8A"/>
  </linearGradient>
  <clipPath id="tile"><rect x="8" y="8" width="240" height="240" rx="56"/></clipPath>
  <clipPath id="photo"><rect x="{ix}" y="{iy}" width="{iw}" height="{ih}" rx="7"/></clipPath>
</defs>
<rect x="8" y="8" width="240" height="240" rx="56" fill="url(#bg)"/>
<g clip-path="url(#tile)" stroke="#FFFFFF" stroke-opacity="0.42" stroke-linecap="round">
{web}
</g>
<line x1="{CENTER[0]}" y1="{CENTER[1]}" x2="{ax:.1f}" y2="{ay:.1f}" stroke="#FFFFFF"
      stroke-width="{thread_w}" stroke-linecap="round"/>
{trail}
<circle cx="{CENTER[0]}" cy="{CENTER[1]}" r="{knot + 2}" fill="#FFFFFF"/>
<g transform="rotate({tilt} {ox} {oy})">
  <rect x="{x + 3}" y="{y + 7}" width="{w}" height="{h}" rx="14" fill="#0F172A" fill-opacity="0.28"/>
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#FFFFFF"/>
  <g clip-path="url(#photo)">
    <rect x="{ix}" y="{iy}" width="{iw}" height="{ih}" fill="#DBEAFE"/>
    <circle cx="{ix + iw * 0.76}" cy="{iy + ih * 0.3}" r="{ih * 0.13}" fill="#F59E0B"/>
    <path d="M{ix - 2},{iy + ih + 2} L{ix + iw * 0.36},{iy + ih * 0.42} L{ix + iw * 0.68},{iy + ih + 2} Z" fill="#2563EB"/>
    <path d="M{ix + iw * 0.44},{iy + ih + 2} L{ix + iw * 0.72},{iy + ih * 0.6} L{ix + iw + 2},{iy + ih + 2} Z" fill="#1D4ED8"/>
  </g>
</g>
<circle cx="{ax:.1f}" cy="{ay:.1f}" r="{knot}" fill="#FFFFFF" stroke="#1E3A8A" stroke-width="{2 if small else 2.5}"/>
</svg>'''


PAGE = """<!doctype html><html><body><pre id="out"></pre><script>
const JOBS = %s;
async function draw(svg, w, h, bg) {
  const img = new Image();
  img.src = "data:image/svg+xml;base64," + btoa(svg);
  await img.decode();
  return img;
}
(async () => {
  const out = {};
  for (const [size, svg] of JOBS.icons) {
    const img = await draw(svg);
    const c = document.createElement("canvas");
    c.width = c.height = size;
    c.getContext("2d").drawImage(img, 0, 0, size, size);
    out[size] = c.toDataURL("image/png");
  }
  // Vorschaubogen: alle Größen auf hellem und dunklem Grund
  const sheet = document.createElement("canvas");
  sheet.width = 760; sheet.height = 400;
  const g = sheet.getContext("2d");
  for (const [row, bg] of [[0, "#F3F4F6"], [1, "#111113"]]) {
    g.fillStyle = bg; g.fillRect(0, row * 200, 760, 200);
    let x = 24;
    for (const [size, svg] of JOBS.icons) {
      const img = await draw(svg);
      g.drawImage(img, x, row * 200 + 100 - size / 2, size, size);
      x += size + 24;
    }
  }
  out.preview = sheet.toDataURL("image/png");
  document.getElementById("out").textContent = JSON.stringify(out);
})();
</script></body></html>"""


def render() -> dict[str, bytes]:
    jobs = {"icons": [[s, svg(small=s <= 32)] for s in SIZES]}
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "icon.html"
        page.write_text(PAGE % json.dumps(jobs), encoding="utf-8")
        result = subprocess.run(
            [str(EDGE), "--headless=new", "--disable-gpu", "--virtual-time-budget=5000",
             f"--user-data-dir={Path(tmp) / 'profile'}", "--dump-dom", page.as_uri()],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
    match = re.search(r'<pre id="out">(.*?)</pre>', result.stdout, re.S)
    if not match or not match.group(1):
        raise SystemExit(f"Edge hat nichts geliefert:\n{result.stderr[-2000:]}")
    data = json.loads(html.unescape(match.group(1)))
    return {k: base64.b64decode(v.split(",", 1)[1]) for k, v in data.items()}


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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preview", type=Path, help="Vorschaubogen als PNG speichern")
    parser.add_argument("--svg", type=Path, help="großes Motiv zusätzlich als SVG speichern")
    args = parser.parse_args()

    pngs = render()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.ico").write_bytes(ico([(s, pngs[str(s)]) for s in SIZES]))
    (OUT / "icon.png").write_bytes(pngs["256"])
    if args.preview:
        args.preview.write_bytes(pngs["preview"])
    if args.svg:
        args.svg.write_text(svg(small=False), encoding="utf-8")
    print(f"geschrieben: {OUT / 'icon.ico'}")


if __name__ == "__main__":
    main()
