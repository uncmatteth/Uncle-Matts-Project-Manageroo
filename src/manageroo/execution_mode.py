from __future__ import annotations

import os
from collections.abc import Mapping


EXECUTION_MODE_ENV = "MANAGEROO_EXECUTION_MODE"
OPERATOR_MODE = "operator"
STRUCTURED_WORKER_MODE = "structured-worker"


def current_execution_mode(environ: Mapping[str, str] | None = None) -> str:
    value = (environ or os.environ).get(EXECUTION_MODE_ENV, "").strip()
    if value == STRUCTURED_WORKER_MODE:
        return STRUCTURED_WORKER_MODE
    return OPERATOR_MODE


def structured_worker_environment() -> dict[str, str]:
    return {EXECUTION_MODE_ENV: STRUCTURED_WORKER_MODE}


def operator_continuity_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return current_execution_mode(environ) == OPERATOR_MODE
