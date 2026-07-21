"""Uncle Matt's Project Manageroo."""

__version__ = "2026.7.19.1"


def _install_controller_policies() -> None:
    # Keep the large orchestrator focused on lifecycle control while independently
    # tested policy modules remain the package-wide authorities for completion,
    # proof-plan validation, discovery, evidence retrieval, repair, and release proof.
    from . import checks as checks_module
    from . import config as config_module
    from . import context as context_module
    from . import evidence as evidence_module
    from . import evidence_policy as evidence_policy_module
    from . import intent_lock as intent_lock_module
    from . import orchestrator as orchestrator_module
    from . import release_ready as release_ready_module
    from . import stack_update as stack_update_module
    from .acceptance import build_acceptance_evidence
    from .config_mutation_policy import install_config_mutation_policy
    from .context_hardening import install_context_hardening
    from .discovery_policy import install_discovery_policy
    from .evidence_artifact_guard import install_evidence_artifact_guard
    from .evidence_hardening import install_evidence_hardening
    from .evidence_policy import install_evidence_policy
    from .external_repair_policy import install_external_repair_policy
    from .intent_audit_policy import install_intent_audit_policy
    from .plan_proof_policy import install_plan_proof_policy
    from .release_proof_policy import install_release_proof_policy
    from .release_ready_policy import install_release_ready_policy
    from .stack_update_policy import install_stack_update_policy

    install_config_mutation_policy(config_module, checks_module)
    install_context_hardening(context_module)
    install_evidence_hardening(evidence_module, evidence_policy_module)
    install_intent_audit_policy(intent_lock_module)
    install_stack_update_policy(stack_update_module)
    orchestrator_module.build_acceptance_evidence = build_acceptance_evidence
    install_plan_proof_policy(orchestrator_module)
    install_external_repair_policy(orchestrator_module)
    install_discovery_policy(orchestrator_module)
    install_evidence_policy(orchestrator_module)
    install_evidence_artifact_guard(orchestrator_module)
    install_release_proof_policy(orchestrator_module)
    install_release_ready_policy(release_ready_module)


_install_controller_policies()
del _install_controller_policies
