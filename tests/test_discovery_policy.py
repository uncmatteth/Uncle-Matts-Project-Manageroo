import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from manageroo.discovery_policy import install_discovery_policy


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


if __name__ == "__main__":
    unittest.main()
