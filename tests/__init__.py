"""Repository test bootstrap for direct ``python -m unittest discover`` runs."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    src_text = str(_SRC)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
