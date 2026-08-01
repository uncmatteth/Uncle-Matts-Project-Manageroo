from __future__ import annotations

from typing import Any


def install_context_hardening(context_module: Any) -> None:
    """Compatibility marker; ContextCompiler now owns the hardened renderer."""
    if getattr(context_module, "_manageroo_context_hardening_installed", False):
        return
    context_module._manageroo_context_hardening_installed = True
