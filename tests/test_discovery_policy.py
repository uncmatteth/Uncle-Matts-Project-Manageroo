import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import manageroo.discovery_policy as discovery_policy
from manageroo.discovery_policy import (
    apply_resolved_decisions,
    decisions_fully_resolved,
    install_discovery_policy,
)
from manageroo.errors import ValidationError
from manageroo.util import atomic_write_json, read_json, sha256_json


class _Artifacts:
    def __init__(self, root: Path):
        self.root = root
        self.writes = {}

    def write_json(self, relative, data, lock=False):
        self.writes[relative] = {"data": data, "lock": lock}
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path


class DiscoveryPolicyTests(unittest.TestCase):
    def _module(self, root: Path, configured_parallel: int = 8):
        class FakeOrchestrator:
            def __init__(self):
                self.source_repo = root
                self.artifacts = _Artifacts(root / "artifacts")
                self.continuing = False
                self.run_root = root / ".manageroo" / "runs" / "test"
                self.calls = []

            def _max_parallel_agent_calls(self):
                return configured_parallel

            def _blocking_decisions_path(self):
                return self.run_root / "artifacts" / "planning" / "blocking-decisions.json"

            def _call(self, *args, **kwargs):
                self.calls.append(kwargs)
                return {"ok": True}

            def run(self, *args, **kwargs):
                return {"status": "COMPLETE"}

        module = SimpleNamespace(Orchestrator=FakeOrchestrator)
        install_discovery_policy(module)
        return module

    def test_host_hardware_never_changes_configured_parallelism(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch(
                "manageroo.discovery_policy.host_capacity",
                return_value={
                    "manageroo_core": {
                        "hardware_agnostic": True,
                        "auto_tunes_worker_concurrency_from_hardware": False,
                    }
                },
            ):
                instance = self._module(root, configured_parallel=8).Orchestrator()
                self.assertEqual(instance._max_parallel_agent_calls(), 8)

    def test_product_analyst_receives_hardware_context_without_autotune_instruction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capacity = {
                "manageroo_core": {
                    "hardware_agnostic": True,
                    "auto_tunes_worker_concurrency_from_hardware": False,
                },
                "notes": [],
            }
            with patch(
                "manageroo.discovery_policy.host_capacity",
                return_value=capacity,
            ):
                instance = self._module(root, configured_parallel=4).Orchestrator()
                instance._call(
                    role="product-analyst",
                    instructions="Product brief:\nBuild a login page",
                )
            packet = instance.calls[0]["instructions"]
            self.assertIn("Manageroo unknown-unknowns preflight", packet)
            self.assertIn("Development-host hardware profile", packet)
            self.assertIn("MUST NOT be used to auto-tune Manageroo worker concurrency", packet)
            self.assertIn("identity-and-access", packet)
            self.assertIn("discovery/system-capacity.json", instance.artifacts.writes)
            self.assertIn(
                "discovery/unknown-unknowns-preflight.json",
                instance.artifacts.writes,
            )

    def test_continuation_reuses_locked_capacity_and_preflight_in_worker_spec(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            instance = self._module(root, configured_parallel=4).Orchestrator()
            instance.continuing = True
            discovery = instance.artifacts.root / "discovery"
            discovery.mkdir(parents=True)
            atomic_write_json(
                discovery / "system-capacity.json",
                {"disk": {"free_gib": 170.5}, "saved_capacity": True},
            )
            atomic_write_json(
                discovery / "unknown-unknowns-preflight.json",
                {"saved_preflight": True},
            )

            with patch(
                "manageroo.discovery_policy.host_capacity",
                return_value={"disk": {"free_gib": 171.5}},
            ) as host_probe, patch(
                "manageroo.discovery_policy.build_discovery_preflight",
                return_value={"saved_preflight": False},
            ) as preflight_builder:
                instance._call(
                    role="product-analyst",
                    instructions="Product brief:\nBuild a login page",
                )

            packet = instance.calls[0]["instructions"]
            self.assertIn('"free_gib": 170.5', packet)
            self.assertIn('"saved_preflight": true', packet)
            self.assertNotIn('"free_gib": 171.5', packet)
            host_probe.assert_not_called()
            preflight_builder.assert_not_called()

    def test_fully_resolved_rejects_malformed_product_decisions(self):
        malformed_decision_sets = [
            ["malformed"],
            [{"id": "known", "chosen": "yes"}, "malformed"],
        ]
        for decisions in malformed_decision_sets:
            with self.subTest(decisions=decisions), tempfile.TemporaryDirectory() as temp:
                run_root = Path(temp)
                planning = run_root / "artifacts" / "planning"
                planning.mkdir(parents=True)
                (planning / "product-model.json").write_text(
                    json.dumps({"blocking_decisions": decisions}),
                    encoding="utf-8",
                )
                (planning / "decision-resolution.json").write_text("{}", encoding="utf-8")

                with self.assertRaises(ValidationError):
                    decisions_fully_resolved(run_root)

    def test_interrupted_decision_claim_is_recovered_on_next_application(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "product-model.json",
                {
                    "blocking_decisions": [
                        {
                            "id": "DEPLOY-1",
                            "options": ["Blue", "Green"],
                            "chosen": None,
                        }
                    ]
                },
            )
            resolved_path = planning / "resolved-decisions.json"
            atomic_write_json(
                resolved_path,
                {"answers": [{"id": "DEPLOY-1", "chosen": "Blue"}]},
            )

            real_claim = discovery_policy._claim_resolved_input

            def interrupt_after_claim(path: Path) -> Path | None:
                claimed = real_claim(path)
                self.assertIsNotNone(claimed)
                raise KeyboardInterrupt

            with patch(
                "manageroo.discovery_policy._claim_resolved_input",
                side_effect=interrupt_after_claim,
            ), self.assertRaises(KeyboardInterrupt):
                apply_resolved_decisions(run_root)

            self.assertFalse(resolved_path.exists())
            self.assertEqual(
                len(list(planning.glob(".resolved-decisions.json.claimed-*.json"))),
                1,
            )

            self.assertTrue(apply_resolved_decisions(run_root))
            product = read_json(planning / "product-model.json")
            self.assertEqual(product["blocking_decisions"][0]["chosen"], "Blue")
            self.assertTrue(decisions_fully_resolved(run_root))
            self.assertEqual(
                list(planning.glob(".resolved-decisions.json.claimed-*.json")),
                [],
            )

    def test_interrupted_claim_conflicts_with_a_new_submission_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "product-model.json",
                {
                    "blocking_decisions": [
                        {
                            "id": "DEPLOY-1",
                            "options": ["Blue", "Green"],
                            "chosen": None,
                        }
                    ]
                },
            )
            resolved_path = planning / "resolved-decisions.json"
            atomic_write_json(
                resolved_path,
                {"answers": [{"id": "DEPLOY-1", "chosen": "Blue"}]},
            )
            claimed_path = discovery_policy._claim_resolved_input(resolved_path)
            self.assertIsNotNone(claimed_path)
            atomic_write_json(
                resolved_path,
                {"answers": [{"id": "DEPLOY-1", "chosen": "Green"}]},
            )

            with self.assertRaisesRegex(
                ValidationError,
                "Multiple resolved decision submissions remain",
            ):
                apply_resolved_decisions(run_root)

            self.assertEqual(
                read_json(resolved_path)["answers"],
                [{"id": "DEPLOY-1", "chosen": "Green"}],
            )
            self.assertEqual(
                read_json(claimed_path)["answers"],
                [{"id": "DEPLOY-1", "chosen": "Blue"}],
            )

    def test_concurrent_decision_applications_serialize_and_keep_artifacts_consistent(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "product-model.json",
                {
                    "blocking_decisions": [
                        {
                            "id": "DEPLOY-1",
                            "options": ["Blue", "Green"],
                            "chosen": None,
                        }
                    ]
                },
            )
            atomic_write_json(
                planning / "resolved-decisions.json",
                {"answers": [{"id": "DEPLOY-1", "chosen": "Blue"}]},
            )

            first_claimed = threading.Event()
            release_first = threading.Event()
            second_claimed = threading.Event()
            claim_guard = threading.Lock()
            claim_count = 0
            real_claim = discovery_policy._claim_resolved_input
            results: list[bool] = []
            errors: list[BaseException] = []

            def coordinated_claim(path: Path) -> Path | None:
                nonlocal claim_count
                claimed = real_claim(path)
                if claimed is None:
                    return None
                with claim_guard:
                    claim_count += 1
                    claim_number = claim_count
                if claim_number == 1:
                    first_claimed.set()
                    if not release_first.wait(timeout=5):
                        raise TimeoutError("test did not release the first decision claim")
                else:
                    second_claimed.set()
                return claimed

            def apply() -> None:
                try:
                    results.append(apply_resolved_decisions(run_root))
                except BaseException as exc:
                    errors.append(exc)

            with patch(
                "manageroo.discovery_policy._claim_resolved_input",
                side_effect=coordinated_claim,
            ):
                first = threading.Thread(target=apply)
                second = threading.Thread(target=apply)
                first.start()
                self.assertTrue(first_claimed.wait(timeout=5))
                atomic_write_json(
                    planning / "resolved-decisions.json",
                    {"answers": [{"id": "DEPLOY-1", "chosen": "Green"}]},
                )
                second.start()
                try:
                    self.assertFalse(second_claimed.wait(timeout=0.2))
                finally:
                    release_first.set()
                first.join(timeout=5)
                second.join(timeout=5)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(results, [True])
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ValidationError)
            self.assertIn("conflicts with the already-applied choice", str(errors[0]))

            product = read_json(planning / "product-model.json")
            resolution = read_json(planning / "decision-resolution.json")
            self.assertEqual(product["blocking_decisions"][0]["chosen"], "Blue")
            self.assertEqual(
                resolution["answers"],
                [{"id": "DEPLOY-1", "chosen": "Blue"}],
            )
            self.assertEqual(resolution["product_model_sha256"], sha256_json(product))
            self.assertEqual(
                read_json(planning / "resolved-decisions.json")["answers"],
                [{"id": "DEPLOY-1", "chosen": "Green"}],
            )


if __name__ == "__main__":
    unittest.main()
