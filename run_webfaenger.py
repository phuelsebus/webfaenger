"""Startskript für PyInstaller (braucht eine Datei statt `python -m webfaenger`)."""

import sys

from webfaenger.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
