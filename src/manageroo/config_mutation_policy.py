from __future__ import annotations

from typing import Any

from .branding import PROJECT_DIR
from .config_lock import config_mutation_lock


def install_config_mutation_policy(config_module: Any, checks_module: Any) -> None:
    if getattr(config_module, "_manageroo_config_mutation_policy_installed", False):
        return

    original_preset = config_module.apply_agent_preset
    original_add_gate = checks_module.add_check_gate

    def apply_agent_preset_locked(repo, preset_name: str):
        config_path = repo / PROJECT_DIR / "config.toml"
        with config_mutation_lock(config_path):
            return original_preset(repo, preset_name)

    def add_check_gate_locked(repo, **kwargs):
        config_path = repo / PROJECT_DIR / "config.toml"
        with config_mutation_lock(config_path):
            return original_add_gate(repo, **kwargs)

    config_module.apply_agent_preset = apply_agent_preset_locked
    checks_module.add_check_gate = add_check_gate_locked
    config_module._manageroo_config_mutation_policy_installed = True
