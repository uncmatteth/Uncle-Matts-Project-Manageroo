from __future__ import annotations

from typing import Any

from .external_repair_policy import run_external_review_repair_lanes


def install_external_repair_policy(orchestrator_module: Any) -> None:
    """Install the command-owned external review/repair lane on Orchestrator.

    Keep installation idempotent because importing ``manageroo`` may occur repeatedly in
    installer and test processes. The implementation remains in
    ``external_repair_policy``; this module only binds it onto the controller class.
    """
    cls = orchestrator_module.Orchestrator
    if getattr(cls, "_manageroo_external_repair_policy_installed", False):
        return
    cls._run_external_review_repair_lanes = run_external_review_repair_lanes
    cls._manageroo_external_repair_policy_installed = True
