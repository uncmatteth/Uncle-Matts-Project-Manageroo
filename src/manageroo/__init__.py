"""Uncle Matt's Project Manageroo."""

__version__ = "2026.7.17.1"


def _install_completion_policy() -> None:
    # Keep the large orchestrator focused on lifecycle control while installing the
    # independently tested completion policy as the single package-wide authority.
    from . import orchestrator as orchestrator_module
    from .acceptance import build_acceptance_evidence

    orchestrator_module.build_acceptance_evidence = build_acceptance_evidence


_install_completion_policy()
del _install_completion_policy
