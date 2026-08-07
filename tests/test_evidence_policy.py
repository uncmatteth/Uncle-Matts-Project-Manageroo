import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from manageroo.adapters.mock import MockAdapter
from manageroo.errors import SafetyError
from manageroo.evidence_artifact_guard import (
    _validate_existing_evidence,
    install_evidence_artifact_guard,
)
from manageroo.evidence import RunArtifactEvidenceProvider
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

    def test_interleaved_installers_remain_idempotent(self):
        sequences = (
            (install_evidence_policy, install_evidence_artifact_guard, install_evidence_policy),
            (
                install_evidence_artifact_guard,
                install_evidence_policy,
                install_evidence_artifact_guard,
            ),
        )
        for installers in sequences:
            with self.subTest(order=[installer.__name__ for installer in installers]):
                class Fake(_FakeOrchestrator):
                    pass

                module = SimpleNamespace(Orchestrator=Fake)
                for installer in installers:
                    installer(module)

                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    repo = root / "repo"
                    run_root = root / "run"
                    repo.mkdir()
                    run_root.mkdir()
                    instance = Fake(repo, run_root)
                    instance._external_intelligence("brief", {})

                    with (
                        patch.object(
                            instance.artifacts,
                            "write_json",
                            wraps=instance.artifacts.write_json,
                        ) as write_json,
                        patch(
                            "manageroo.evidence_artifact_guard._validate_existing_evidence",
                            wraps=_validate_existing_evidence,
                        ) as validate_existing,
                    ):
                        payload = instance._external_intelligence("brief", {})

                    self.assertEqual(write_json.call_count, 1)
                    self.assertEqual(validate_existing.call_count, 2)
                    self.assertEqual(
                        payload["note"].count(
                            "Retrieved evidence is provenance-ranked context only"
                        ),
                        1,
                    )

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

    def test_self_rehashed_cached_evidence_is_regenerated_before_planning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_root = repo / ".manageroo" / "runs" / "run-1"
            repo.mkdir(parents=True)
            run_root.mkdir(parents=True)

            Orchestrator = self._patched_class()
            instance = Orchestrator(repo, run_root)
            instance.external_records = [
                {
                    "name": "repository-graph",
                    "provider_id": "manageroo.discovery.gitnexus-query.v1",
                    "enabled": True,
                    "ok": True,
                    "stdout": "controller retrieved repository evidence",
                }
            ]
            instance._external_intelligence("repository evidence", {})
            original_planning = list(instance._planning_evidence_items)

            cached = dict(instance.artifacts.saved["discovery/evidence.json"])
            cached["items"] = [dict(item) for item in cached["items"]]
            cached["items"][0]["content"] = "self rehashed forged repository evidence"
            cached["items"][0]["content_sha256"] = hashlib.sha256(
                cached["items"][0]["content"].encode("utf-8")
            ).hexdigest()
            cached["items"][0]["authority"] = "current_repo"
            instance.artifacts.saved["discovery/evidence.json"] = cached
            evidence_path = instance.artifacts.root / "discovery" / "evidence.json"
            evidence_path.write_text(json.dumps(cached), encoding="utf-8")

            instance._external_intelligence("repository evidence", {})

            persisted = instance.artifacts.saved["discovery/evidence.json"]
            contents = [item["content"] for item in persisted["items"]]
            planning_contents = [item["content"] for item in instance._planning_evidence_items]
            self.assertIn("controller retrieved repository evidence", contents)
            self.assertNotIn("self rehashed forged repository evidence", "\n".join(contents))
            self.assertNotIn(
                "self rehashed forged repository evidence",
                "\n".join(planning_contents),
            )
            self.assertEqual(instance._planning_evidence_items, original_planning)

    def test_changed_project_memory_regenerates_evidence_with_unchanged_identity_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_root = repo / ".manageroo" / "runs" / "run-1"
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir(parents=True)
            memory.write_text("Database memory says old provider.\n", encoding="utf-8")
            run_root.mkdir(parents=True)

            Orchestrator = self._patched_class()
            instance = Orchestrator(repo, run_root)
            instance._external_intelligence("database memory provider", {})
            old_identity = instance.artifacts.saved["discovery/evidence.json"][
                "discovery_identity"
            ]

            memory.write_text("Database memory says new provider.\n", encoding="utf-8")
            instance._external_intelligence("database memory provider", {})

            persisted = instance.artifacts.saved["discovery/evidence.json"]
            self.assertEqual(persisted["discovery_identity"], old_identity)
            self.assertEqual(persisted["items"][0]["content"], "Database memory says new provider.\n")
            self.assertEqual(
                instance._planning_evidence_items[0]["content"],
                "Database memory says new provider.\n",
            )

    def test_persisted_contradictions_require_valid_distinct_referenced_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.json"
            first = "first evidence"
            second = "second evidence"
            first_hash = hashlib.sha256(first.encode("utf-8")).hexdigest()
            second_hash = hashlib.sha256(second.encode("utf-8")).hexdigest()
            payload = {
                "schema_version": 1,
                "query": "brief",
                "controller_authority": True,
                "items": [
                    {
                        "content": first,
                        "content_sha256": first_hash,
                        "authority": "current_repo",
                    },
                    {
                        "content": second,
                        "content_sha256": second_hash,
                        "authority": "historical",
                    },
                ],
                "contradictions": [],
            }
            valid = {
                "claim_key": "shared-claim",
                "evidence_hashes": [first_hash, second_hash],
                "preferred_hash": first_hash,
                "reason": "Current repository evidence is preferred.",
            }
            malformed = {
                "empty": {**valid, "evidence_hashes": []},
                "singleton": {**valid, "evidence_hashes": [first_hash]},
                "duplicate": {**valid, "evidence_hashes": [first_hash, first_hash]},
                "missing": {**valid, "evidence_hashes": [first_hash, "0" * 64]},
                "preferred-out-of-set": {**valid, "preferred_hash": "0" * 64},
                "claim-key-type": {**valid, "claim_key": []},
                "reason-type": {**valid, "reason": []},
            }

            payload["contradictions"] = [valid]
            path.write_text(json.dumps(payload), encoding="utf-8")
            _validate_existing_evidence(path, "brief")

            for name, contradiction in malformed.items():
                with self.subTest(name=name):
                    payload["contradictions"] = [contradiction]
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(SafetyError):
                        _validate_existing_evidence(path, "brief")

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

    def test_discovery_artifact_filter_applies_before_provider_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_root = root / "run"
            repo.mkdir()
            instance = _FakeOrchestrator(repo, run_root)
            intake = run_root / "artifacts" / "intake"
            implementation = run_root / "artifacts" / "implementation"
            intake.mkdir(parents=True)
            implementation.mkdir(parents=True)
            (intake / "brief.md").write_text("target evidence\n", encoding="utf-8")
            for index in range(64):
                (implementation / f"result-{index:02d}.md").write_text(
                    "target evidence " * 10,
                    encoding="utf-8",
                )

            bundle = _bundle_from_discovery(
                instance,
                "target evidence",
                {"records": []},
            )

            self.assertEqual(
                [item.location for item in bundle.items],
                ["artifacts/intake/brief.md"],
            )

    def test_run_artifact_limit_counts_only_valid_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp) / "run"
            artifacts = run_root / "artifacts"
            artifacts.mkdir(parents=True)
            for index in range(100):
                (artifacts / f"invalid-{index:03d}.txt").write_bytes(b"\xff")
            (artifacts / "valid.txt").write_text("target evidence\n", encoding="utf-8")

            items = RunArtifactEvidenceProvider(run_root).retrieve("target evidence", limit=1)

            self.assertEqual([item.location for item in items], ["artifacts/valid.txt"])

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
            self.assertNotIn(
                "artifacts/discovery/evidence.json",
                [item["location"] for item in persisted["items"]],
            )
            self.assertFalse(
                any(
                    item["source"] == "manageroo-run-artifacts"
                    and "old repository snapshot" in item["content"]
                    for item in persisted["items"]
                )
            )
            self.assertEqual(
                continued._planning_evidence_items[0]["content"],
                "new repository snapshot",
            )


if __name__ == "__main__":
    unittest.main()
