import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_package_release():
    spec = importlib.util.spec_from_file_location(
        "manageroo_package_release_hardening",
        ROOT / "scripts" / "package_release.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HARDENING_MODULES = {
    "src/manageroo/acceptance.py",
    "src/manageroo/chiptune_policy.py",
    "src/manageroo/config_mutation_policy.py",
    "src/manageroo/context_hardening.py",
    "src/manageroo/discovery_policy.py",
    "src/manageroo/discovery_preflight.py",
    "src/manageroo/entrypoint_policy.py",
    "src/manageroo/evidence.py",
    "src/manageroo/evidence_artifact_guard.py",
    "src/manageroo/evidence_hardening.py",
    "src/manageroo/evidence_policy.py",
    "src/manageroo/external_repair_policy.py",
    "src/manageroo/intent_audit_policy.py",
    "src/manageroo/plan_proof_policy.py",
    "src/manageroo/project_initialization_policy.py",
    "src/manageroo/release_proof_policy.py",
    "src/manageroo/release_ready_policy.py",
    "src/manageroo/skill_pack_policy.py",
    "src/manageroo/stack_doctor_policy.py",
    "src/manageroo/stack_update_policy.py",
    "src/manageroo/adapters/budget.py",
    "src/manageroo/adapters/pool.py",
    "src/manageroo/adapters/transactional.py",
}

BEHAVIORAL_REGRESSION_TESTS = {
    "tests/test_acceptance_evidence.py",
    "tests/test_clawpatch_regressions.py",
    "tests/test_clawpatch_remaining_regressions.py",
    "tests/test_cli_smoke.py",
    "tests/test_decision_regressions.py",
    "tests/test_decision_workflow.py",
    "tests/test_discovery_cli.py",
    "tests/test_discovery_policy.py",
    "tests/test_discovery_preflight.py",
    "tests/test_entrypoint_safety.py",
    "tests/test_evidence.py",
    "tests/test_evidence_policy.py",
    "tests/test_external_repair_policy.py",
    "tests/test_external_repair_resume.py",
    "tests/test_final_clawpatch_regressions.py",
    "tests/test_install_repair.py",
    "tests/test_integration_config_regressions.py",
    "tests/test_integrations.py",
    "tests/test_jobs.py",
    "tests/test_parallel_worker_logging.py",
    "tests/test_plan_proof_policy.py",
    "tests/test_release_driver.py",
    "tests/test_release_ready_missing_executable.py",
    "tests/test_remaining_audit_regressions.py",
    "tests/test_scope_and_skill_path_hardening.py",
    "tests/test_skill_pack_transaction.py",
    "tests/test_stack_doctor.py",
    "tests/test_stack_update.py",
    "tests/test_transactional_adapter_hardening.py",
    "tests/test_transactional_history_and_pristine.py",
    "tests/test_truth_contract_production.py",
    "tests/test_worker_attempt_isolation.py",
    "tests/test_worker_pool.py",
    "tests/test_workspace.py",
}


class ReleaseHardeningContractTests(unittest.TestCase):
    def test_hardened_controller_modules_and_behavioral_regressions_are_packaged(self):
        package_release = _load_package_release()
        source = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}
        end_user = {path.relative_to(ROOT).as_posix() for path in package_release.end_user_files()}
        required = {
            "sitecustomize.py",
            "docs/DISCOVERY_AND_CAPACITY.md",
            "docs/EVIDENCE_RETRIEVAL.md",
            "docs/HOST_INTEGRATION.md",
            "scripts/finalize_gitnexus.py",
            "scripts/release.py",
            "src/manageroo/host_skills.py",
            "src/manageroo/system_capacity.py",
            "src/manageroo/stack_update.py",
            *HARDENING_MODULES,
            *BEHAVIORAL_REGRESSION_TESTS,
        }
        self.assertTrue(required <= source, sorted(required - source))
        end_user_required = {
            item
            for item in required
            if item.startswith("src/")
            or item.startswith("docs/")
            or item in {"scripts/release.py", "scripts/finalize_gitnexus.py", "sitecustomize.py"}
        }
        self.assertTrue(end_user_required <= end_user, sorted(end_user_required - end_user))

    def test_behavior_critical_hardening_is_covered_by_executable_tests(self):
        missing = [
            relative
            for relative in sorted(BEHAVIORAL_REGRESSION_TESTS)
            if not (ROOT / relative).is_file()
        ]
        self.assertEqual(missing, [])

    def test_public_boundary_is_generic_and_current(self):
        public_files = [
            ROOT / "README.md",
            ROOT / "GITHUB_DESCRIPTION.md",
            ROOT / "LOCAL_SETUP.md",
            ROOT / "PUBLISH_TO_GITHUB.md",
            ROOT / "GIVE-THIS-TO-YOUR-IDE-AGENT.md",
            *sorted((ROOT / "docs").glob("*.md")),
        ]
        combined = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in public_files if path.is_file())
        self.assertNotIn("HOST_AND_TOS_INTEGRATION", combined)
        self.assertNotIn("Tommy's workstation", combined)
        self.assertNotIn("Host / tOS", combined)
        self.assertIn("skill-vetter", combined)
        self.assertIn("GitNexus", combined)
        self.assertIn("Evidence Retrieval Architecture", combined)
        self.assertIn("retrieves evidence", combined)

    def test_release_stays_local_and_action_free(self):
        workflows = ROOT / ".github" / "workflows"
        self.assertFalse(workflows.exists() and any(workflows.iterdir()))
        publish = (ROOT / "PUBLISH_TO_GITHUB.md").read_text(encoding="utf-8")
        self.assertIn("does not use GitHub Actions", publish)
        self.assertIn("python3 scripts/release.py", publish)
        self.assertIn("manageroo prove", publish)
        self.assertIn("scripts/verify_release.py", publish)
        self.assertIn("scripts/package_release.py", publish)


if __name__ == "__main__":
    unittest.main()
