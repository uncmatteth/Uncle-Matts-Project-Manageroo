from __future__ import annotations

from typing import Any


def install_chiptune_policy(module: Any) -> None:
    if getattr(module, "_manageroo_chiptune_policy_installed", False):
        return
    module._manageroo_chiptune_policy_installed = True
