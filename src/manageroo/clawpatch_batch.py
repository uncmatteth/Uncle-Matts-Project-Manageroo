from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import SafetyError


_DISABLED = (
    "The report-derived Clawpatch batch workflow is disabled. "
    "Use `manageroo clawpatch release-sweep`; it automates Clawpatch's structured one-finding "
    "workflow and stops on the first failed gate."
)


def open_finding_ids(repo: Path) -> tuple[list[str], str]:
    del repo
    raise SafetyError(_DISABLED)


def batch_fix_open_findings(
    repo: Path,
    *,
    apply: bool = False,
    limit: int = 0,
    commit_each: bool = True,
) -> dict[str, Any]:
    del repo, apply, limit, commit_each
    raise SafetyError(_DISABLED)


def format_batch_fix(report: dict[str, Any]) -> str:
    del report
    raise SafetyError(_DISABLED)
