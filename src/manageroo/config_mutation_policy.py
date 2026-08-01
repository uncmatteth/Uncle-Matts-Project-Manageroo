from __future__ import annotations

from typing import Any


def install_config_mutation_policy(config_module: Any, checks_module: Any) -> None:
    if getattr(config_module, "_manageroo_config_mutation_policy_installed", False):
        return
    config_module._manageroo_config_mutation_policy_installed = True
