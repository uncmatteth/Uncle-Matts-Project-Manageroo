from __future__ import annotations

from typing import Any

from .managed_completion_policy import (
    _verify_completion_receipt,
    _write_completion_receipt,
    install_managed_completion_policy,
)
from .managed_contract_common import (
    EXECUTION_INTENT_MUTATING,
    EXECUTION_INTENT_READ_ONLY,
    _load_request_metadata,
)
from .managed_request_binding import _resolve_repository_binding
from .managed_hook_policy import (
    install_managed_contract_entrypoint_policy,
    install_managed_request_policy,
    reset_continuity_state,
)


def install_managed_contract_policy(
    orchestrator_module: Any, continuity_module: Any
) -> None:
    install_managed_request_policy(continuity_module)
    continuity_module._managed_completion_proof = (
        lambda state: _verify_completion_receipt(state, continuity_module)
    )
    install_managed_completion_policy(orchestrator_module, continuity_module)


__all__ = [
    "EXECUTION_INTENT_MUTATING",
    "EXECUTION_INTENT_READ_ONLY",
    "_load_request_metadata",
    "_resolve_repository_binding",
    "_write_completion_receipt",
    "install_managed_contract_entrypoint_policy",
    "install_managed_contract_policy",
    "reset_continuity_state",
]
