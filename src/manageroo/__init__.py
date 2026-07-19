"""Uncle Matt's Project Manageroo."""

__version__ = "2026.7.19.1"


def _install_controller_policies() -> None:
    # Keep the large orchestrator focused on lifecycle control while independently
    # tested policy modules remain the package-wide authorities for completion,
    # proof-plan validation, discovery, and continuation-safe repair behavior.
    from . import orchestrator as orchestrator_module
    from .acceptance import build_acceptance_evidence
    from .discovery_policy import install_discovery_policy
    from .external_repair_policy import install_external_repair_policy
    from .plan_proof_policy import install_plan_proof_policy

    orchestrator_module.build_acceptance_evidence = build_acceptance_evidence
    install_plan_proof_policy(orchestrator_module)
    install_external_repair_policy(orchestrator_module)
    install_discovery_policy(orchestrator_module)


_install_controller_policies()
del _install_controller_policies
