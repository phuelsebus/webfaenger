"""Schreibt die Versionsinfo für PyInstaller (Explorer > Eigenschaften > Details).

Aufruf: python tools/version_info.py <zieldatei>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from webfaenger import __version__  # noqa: E402

PUBLISHER = "Pascal Hülsebus"

numbers = tuple(int(part) for part in (__version__.split(".") + ["0"] * 4)[:4])
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704B0', [
      StringStruct('CompanyName', '{PUBLISHER}'),
      StringStruct('FileDescription', 'Webfänger'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'Webfaenger'),
      StringStruct('OriginalFilename', 'Webfaenger.exe'),
      StringStruct('ProductName', 'Webfänger'),
      StringStruct('ProductVersion', '{__version__}'),
      StringStruct('LegalCopyright', '© 2026 {PUBLISHER}')])]),
    VarFileInfo([VarStruct('Translation', [1031, 1200])])
  ]
)
"""
target = Path(sys.argv[1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(text, encoding="utf-8")
print(__version__)
