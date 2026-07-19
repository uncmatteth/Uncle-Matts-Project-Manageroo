import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from manageroo.evidence_policy import install_evidence_policy


class _Artifacts:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True)
        self.saved = {}

    def write_json(self, relative: str, data, *, lock: bool = False):
        self.saved[relative] = data
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return SimpleNamespace(path=relative)


class _FakeOrchestrator:
    def __init__(self, repo: Path, run_root: Path):
        self.source_repo = repo
        self.run_root = run_root
        self.artifacts = _Artifacts(run_root / "artifacts")
        self.call_payloads = []

    def _artifact_json(self, relative: str):
        return self.artifacts.saved.get(relative)

    def _external_intelligence(self, brief: str, inventory: dict):
        return {"summary": {}, "records": [], "note": "base"}

    def _call(self, *args, **kwargs):
        self.call_payloads.append((args, kwargs))
        return kwargs


class EvidencePolicyTests(unittest.TestCase):
    def _patched_class(self):
        class Fake(_FakeOrchestrator):
            pass

        module = SimpleNamespace(Orchestrator=Fake)
        install_evidence_policy(module)
        return module.Orchestrator

    def test_discovery_writes_ranked_evidence_and_planning_call_receives_bounded_items(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_root = repo / ".manageroo" / "runs" / "run-1"
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir(parents=True)
            memory.write_text("Database migration completed to Neon.\n", encoding="utf-8")
            run_root.mkdir(parents=True)

            Orchestrator = self._patched_class()
            instance = Orchestrator(repo, run_root)
            payload = instance._external_intelligence("database Neon migration", {})

            evidence = instance.artifacts.saved["discovery/evidence.json"]
            self.assertTrue(evidence["controller_authority"])
            self.assertGreaterEqual(len(evidence["items"]), 1)
            self.assertEqual(payload["evidence_bundle"]["item_count"], len(evidence["items"]))
            self.assertNotIn("items", payload["evidence_bundle"])

            result = instance._call(role="plan-compiler", metadata={})
            selected = result["metadata"]["_evidence_items"]
            self.assertGreaterEqual(len(selected), 1)
            self.assertLessEqual(len(selected), 8)
            self.assertTrue(result["metadata"]["_evidence_policy"]["context_only"])
            self.assertTrue(result["metadata"]["_evidence_policy"]["controller_authority"])

    def test_nonplanning_worker_does_not_receive_discovery_evidence_implicitly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_root = repo / ".manageroo" / "runs" / "run-1"
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir(parents=True)
            memory.write_text("Relevant project fact.\n", encoding="utf-8")
            run_root.mkdir(parents=True)

            Orchestrator = self._patched_class()
            instance = Orchestrator(repo, run_root)
            instance._external_intelligence("relevant project", {})
            result = instance._call(role="implementer", metadata={})
            self.assertNotIn("_evidence_items", result["metadata"])


if __name__ == "__main__":
    unittest.main()
