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


class ReleaseHardeningContractTests(unittest.TestCase):
    def test_hardened_controller_modules_and_regressions_are_packaged(self):
        package_release = _load_package_release()
        source = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}
        end_user = {path.relative_to(ROOT).as_posix() for path in package_release.end_user_files()}
        required = {
            "src/manageroo/acceptance.py",
            "src/manageroo/external_repair_policy.py",
            "src/manageroo/adapters/budget.py",
            "src/manageroo/adapters/pool.py",
            "src/manageroo/adapters/transactional.py",
            "tests/test_acceptance_evidence.py",
            "tests/test_external_repair_resume.py",
            "tests/test_release_hardening_contract.py",
            "tests/test_worker_attempt_isolation.py",
            "tests/test_worker_pool.py",
        }
        self.assertTrue(required <= source, sorted(required - source))
        runtime_required = {item for item in required if item.startswith("src/")}
        self.assertTrue(runtime_required <= end_user, sorted(runtime_required - end_user))

    def test_controller_hardening_contract_is_present(self):
        transactional = (ROOT / "src/manageroo/adapters/transactional.py").read_text(
            encoding="utf-8"
        )
        budget = (ROOT / "src/manageroo/adapters/budget.py").read_text(encoding="utf-8")
        repair = (ROOT / "src/manageroo/external_repair_policy.py").read_text(
            encoding="utf-8"
        )
        acceptance = (ROOT / "src/manageroo/acceptance.py").read_text(encoding="utf-8")

        self.assertIn("critical_controller_truth_guard", transactional)
        self.assertIn("pending-workspace-validation.json", transactional)
        self.assertIn("threading.RLock", budget)
        self.assertIn("worker_calls_consumed", budget)
        self.assertIn("resumed_from_checkpoint", repair)
        self.assertIn("Outcome-specific proof binding is missing", acceptance)

    def test_release_stays_local_and_action_free(self):
        workflows = ROOT / ".github" / "workflows"
        self.assertFalse(workflows.exists() and any(workflows.iterdir()))
        publish = (ROOT / "PUBLISH_TO_GITHUB.md").read_text(encoding="utf-8")
        self.assertIn("does not use GitHub Actions", publish)
        self.assertIn("manageroo prove", publish)
        self.assertIn("scripts/verify_release.py", publish)
        self.assertIn("scripts/package_release.py", publish)


if __name__ == "__main__":
    unittest.main()
