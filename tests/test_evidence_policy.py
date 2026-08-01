import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from manageroo.adapters.mock import MockAdapter
from manageroo.evidence_artifact_guard import install_evidence_artifact_guard
from manageroo.evidence_policy import _bundle_from_discovery, install_evidence_policy
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project


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
        self.external_records = []

    def _artifact_json(self, relative: str):
        saved = getattr(self.artifacts, "saved", None)
        if isinstance(saved, dict):
            return saved.get(relative)
        path = self.artifacts.root / relative
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _external_intelligence(self, brief: str, inventory: dict):
        return {"summary": {}, "records": list(self.external_records), "note": "base"}

    def _call(self, *args, **kwargs):
        self.call_payloads.append((args, kwargs))
        return kwargs


class EvidencePolicyTests(unittest.TestCase):
    def _patched_class(self):
        class Fake(_FakeOrchestrator):
            pass

        module = SimpleNamespace(Orchestrator=Fake)
        install_evidence_policy(module)
        install_evidence_artifact_guard(module)
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

    def test_provider_display_names_cannot_grant_current_repository_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_root = root / "run"
            repo.mkdir()
            run_root.mkdir()
            instance = _FakeOrchestrator(repo, run_root)
            records = [
                {
                    "name": name,
                    "enabled": True,
                    "ok": True,
                    "stdout": f"untrusted evidence from {name}",
                }
                for name in ("gitnexus-untrusted", "gitnexus-lookalike", "gitnexus-query")
            ]

            bundle = _bundle_from_discovery(instance, "provider authority", {"records": records})

            self.assertEqual(len(bundle.items), 3)
            for item in bundle.items:
                self.assertEqual(item.authority, "external_knowledge")
                self.assertEqual(item.confidence, 0.70)
                self.assertEqual(item.freshness, 0.70)

    def test_controller_owned_provider_id_grants_configured_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_root = root / "run"
            repo.mkdir()
            run_root.mkdir()
            instance = _FakeOrchestrator(repo, run_root)
            record = {
                "name": "display-name-is-not-authority",
                "provider_id": "manageroo.discovery.gitnexus-query.v1",
                "enabled": True,
                "ok": True,
                "stdout": "trusted repository evidence",
            }

            bundle = _bundle_from_discovery(
                instance,
                "provider authority",
                {"records": [record]},
            )

            self.assertEqual(len(bundle.items), 1)
            self.assertEqual(bundle.items[0].authority, "current_repo")
            self.assertEqual(bundle.items[0].confidence, 0.92)
            self.assertEqual(bundle.items[0].freshness, 1.0)

    def test_repeated_discovery_replaces_stale_repository_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir(parents=True)
            for argv in (
                ["git", "init", "-q", "-b", "main"],
                ["git", "config", "user.name", "MANAGEROO Tests"],
                ["git", "config", "user.email", "tests@local.invalid"],
            ):
                subprocess.run(argv, cwd=repo, check=True)
            snapshot = repo / "snapshot.txt"
            snapshot.write_text("old repository snapshot\n", encoding="utf-8")
            subprocess.run(["git", "add", "snapshot.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)
            initialize_project(repo, agent="mock")
            config = repo / ".manageroo" / "config.toml"
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())",
                "{repo}/snapshot.txt",
            ]
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "gitnexus_query_command = []",
                    "gitnexus_query_command = "
                    + "[" + ", ".join(json.dumps(item) for item in command) + "]",
                ),
                encoding="utf-8",
            )

            instance = Orchestrator(repo, adapter=MockAdapter())
            instance.workspace = instance.mirror.create()
            inventory = {"files": []}
            instance._external_intelligence("repository architecture", inventory)
            self.assertEqual(
                instance._planning_evidence_items[0]["content"],
                "old repository snapshot",
            )

            snapshot.write_text("new repository snapshot\n", encoding="utf-8")
            continued = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=instance.run_id,
                continue_existing=True,
            )
            continued._external_intelligence("repository architecture", inventory)

            persisted = json.loads(
                (continued.artifacts.root / "discovery" / "evidence.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["schema_version"], 2)
            self.assertEqual(len(persisted["discovery_identity"]), 64)
            self.assertEqual(persisted["items"][0]["content"], "new repository snapshot")
            self.assertEqual(persisted["items"][0]["authority"], "current_repo")
            self.assertEqual(
                continued._planning_evidence_items[0]["content"],
                "new repository snapshot",
            )


if __name__ == "__main__":
    unittest.main()
