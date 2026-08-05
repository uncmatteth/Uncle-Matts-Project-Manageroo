from __future__ import annotations

import os
import unittest
from pathlib import Path


def symlink_or_skip(
    case: unittest.TestCase,
    target: str | os.PathLike[str],
    link: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as exc:
        case.skipTest(f"symlink unavailable: {exc}")
