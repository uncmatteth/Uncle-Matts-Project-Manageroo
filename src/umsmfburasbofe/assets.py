from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def asset_path(relative: str) -> Path:
    return Path(str(files("umsmfburasbofe").joinpath("assets", relative)))
