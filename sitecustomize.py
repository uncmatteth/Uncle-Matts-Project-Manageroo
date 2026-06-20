"""Make the src-layout package importable for repository-local verification."""
from pathlib import Path
import sys
src = Path(__file__).resolve().parent / "src"
if src.is_dir() and str(src) not in sys.path:
    sys.path.insert(0, str(src))
