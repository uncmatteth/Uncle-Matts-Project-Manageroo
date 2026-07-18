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

    def test_capacity_recommendation_caps_but_never_increases_configured_parallelism(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch(
                "manageroo.discovery_policy.host_capacity",
                return_value={"recommendations": {"max_parallel_agent_calls": 2}},
            ):
                constrained = self._module(root, configured_parallel=8).Orchestrator()
                self.assertEqual(constrained._max_parallel_agent_calls(), 2)

            with patch(
                "manageroo.discovery_policy.host_capacity",
                return_value={"recommendations": {"max_parallel_agent_calls": 8}},
            ):
                configured = self._module(root, configured_parallel=1).Orchestrator()
                self.assertEqual(configured._max_parallel_agent_calls(), 1)

    def test_product_analyst_receives_capacity_and_unknown_unknowns_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capacity = {
                "recommendations": {
                    "capacity_class": "strong-general-purpose",
                    "max_parallel_agent_calls": 4,
                },
                "warnings": [],
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
            self.assertIn("Detected host capacity", packet)
            self.assertIn("identity-and-access", packet)
            self.assertIn("discovery/system-capacity.json", instance.artifacts.writes)
            self.assertIn(
                "discovery/unknown-unknowns-preflight.json",
                instance.artifacts.writes,
            )


if __name__ == "__main__":
    unittest.main()
