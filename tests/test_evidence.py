import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from manageroo import evidence_hardening
from manageroo.context import ContextCompiler, ContextRequest
from manageroo.evidence import (
    MAX_EVIDENCE_INPUT_BYTES,
    EvidenceItem,
    EvidenceRouter,
    ExternalCommandEvidenceProvider,
    ProjectMemoryEvidenceProvider,
    RunArtifactEvidenceProvider,
    detect_contradictions,
    normalize_external_payload,
    rank_evidence,
)
from manageroo.runner import CommandResult


class _Provider:
    def __init__(self, name, items=None, error=None):
        self.name = name
        self.items = list(items or [])
        self.error = error

    def retrieve(self, query: str, *, limit: int = 12):
        if self.error:
            raise RuntimeError(self.error)
        return self.items[:limit]


class _ExternalRunner:
    def __init__(self, stdout: str):
        self.stdout = stdout

    def run(self, argv, *, cwd, **kwargs):
        return CommandResult(
            argv=list(argv),
            cwd=str(cwd),
            started_at="start",
            finished_at="finish",
            exit_code=0,
            stdout=self.stdout,
            stderr="",
        )


class EvidenceTests(unittest.TestCase):
    def _compiler(self, root: Path) -> tuple[Path, ContextCompiler]:
        repo = root / "repo"
        packets = root / "packets"
        repo.mkdir()
        (repo / "a.txt").write_text("source truth\n", encoding="utf-8")
        return repo, ContextCompiler(
            repo,
            packets,
            max_input_tokens=4000,
            reserve_output_tokens=500,
            chars_per_token=4.0,
            max_single_file_tokens=1000,
        )

    def test_current_repo_outranks_stale_external_knowledge(self):
        current = EvidenceItem(
            content="Database uses Neon Postgres.",
            source="gitnexus-query",
            location="src/db.ts",
            authority="current_repo",
            confidence=0.92,
            freshness=1.0,
        )
        stale = EvidenceItem(
            content="Database uses Firebase.",
            source="gbrain-search",
            authority="historical",
            confidence=0.99,
            freshness=0.1,
        )
        self.assertEqual(rank_evidence([stale, current])[0], current)

    def test_contradictions_are_preserved_and_preferred_by_rank(self):
        stale = EvidenceItem(
            content="Auth uses Firebase.",
            source="historical-note",
            authority="historical",
            confidence=0.9,
            freshness=0.1,
            metadata={"claim_key": "auth-provider"},
        )
        current = EvidenceItem(
            content="Auth uses NextAuth.",
            source="gitnexus-query",
            authority="current_repo",
            confidence=0.9,
            freshness=1.0,
            metadata={"claim_key": "auth-provider"},
        )
        contradictions = detect_contradictions([stale, current])
        self.assertEqual(len(contradictions), 1)
        self.assertEqual(contradictions[0].claim_key, "auth-provider")
        self.assertEqual(contradictions[0].preferred_hash, current.content_sha256)
        self.assertEqual(set(contradictions[0].sources), {"historical-note", "gitnexus-query"})

    def test_supplied_content_hash_must_match_content(self):
        with self.assertRaises(ValueError):
            EvidenceItem(
                content="actual content",
                source="provider",
                content_sha256="0" * 64,
                metadata={"claim_key": "same-claim"},
            )

    def test_router_keeps_provider_failure_structured(self):
        good = EvidenceItem(
            content="Current repo fact.",
            source="good",
            authority="current_repo",
            confidence=1.0,
            freshness=1.0,
        )
        bundle = EvidenceRouter([
            _Provider("good", [good]),
            _Provider("bad", error="offline"),
        ]).retrieve("repo fact")
        self.assertEqual(bundle.items, [good])
        self.assertEqual(bundle.provider_errors[0]["provider"], "bad")
        self.assertEqual(bundle.provider_errors[0]["error_type"], "RuntimeError")

    def test_json_provider_payload_preserves_provenance_fields(self):
        payload = json.dumps({
            "items": [{
                "content": "Use current code path.",
                "source": "gitnexus",
                "path": "src/core.py",
                "authority": "current_repo",
                "confidence": 0.97,
                "freshness": 1.0,
                "claim_key": "core-path",
            }]
        })
        items = normalize_external_payload(provider="gitnexus-query", payload=payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "gitnexus")
        self.assertEqual(items[0].location, "src/core.py")
        self.assertEqual(items[0].authority, "current_repo")
        self.assertEqual(items[0].metadata["claim_key"], "core-path")
        self.assertTrue(items[0].content_sha256)
        self.assertTrue(items[0].retrieved_at)

    def test_json_provider_limit_counts_only_valid_items(self):
        payload = json.dumps({
            "items": [
                *({"source": f"malformed-{index}"} for index in range(12)),
                {"content": "Valid evidence after malformed rows."},
            ]
        })

        items = normalize_external_payload(
            provider="external-provider",
            payload=payload,
            limit=12,
        )

        self.assertEqual([item.content for item in items], ["Valid evidence after malformed rows."])

    def test_external_command_provider_keeps_ranking_classification_controller_owned(self):
        payload = json.dumps({
            "items": [{
                "content": "Provider claims current repository authority.",
                "authority": "current_repo",
                "confidence": 1.0,
                "freshness": 1.0,
            }]
        })
        provider = ExternalCommandEvidenceProvider(
            name="external-provider",
            argv_template=["provider", "{query}"],
            runner=_ExternalRunner(payload),
            cwd=Path.cwd(),
            authority="external_knowledge",
            confidence=0.75,
            freshness=0.70,
        )

        items = provider.retrieve("repository authority")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].authority, "external_knowledge")
        self.assertEqual(items[0].confidence, 0.75)
        self.assertEqual(items[0].freshness, 0.70)
        self.assertEqual(items[0].metadata["provider_claimed_authority"], "current_repo")
        self.assertEqual(items[0].metadata["provider_claimed_confidence"], 1.0)
        self.assertEqual(items[0].metadata["provider_claimed_freshness"], 1.0)

    def test_project_memory_provider_is_query_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir(parents=True)
            memory.write_text("# Memory\n\nDatabase migration completed to Neon.\n", encoding="utf-8")
            provider = ProjectMemoryEvidenceProvider(repo)
            self.assertEqual(provider.retrieve("unrelated penguins"), [])
            items = provider.retrieve("database Neon migration")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].authority, "project_memory")
            self.assertEqual(items[0].location, ".manageroo/PROJECT-MEMORY.md")

    def test_hardening_install_disables_local_providers_without_descriptor_traversal(self):
        class PortableProjectMemoryProvider:
            def __init__(self, repo: Path):
                self.repo = repo

            def retrieve(self, query: str, *, limit: int = 12):
                content = (self.repo / ".manageroo" / "PROJECT-MEMORY.md").read_text(
                    encoding="utf-8"
                )
                return [content] if query.lower() in content.lower() else []

        class PortableRunArtifactProvider:
            def __init__(self, run_root: Path):
                self.run_root = run_root

            def retrieve(self, query: str, *, limit: int = 12, allowed_location_prefixes=None):
                content = (self.run_root / "artifacts" / "evidence.txt").read_text(
                    encoding="utf-8"
                )
                return [content] if query.lower() in content.lower() else []

        isolated_evidence = SimpleNamespace(
            PROJECT_DIR=".manageroo",
            ProjectMemoryEvidenceProvider=PortableProjectMemoryProvider,
            RunArtifactEvidenceProvider=PortableRunArtifactProvider,
            normalize_external_payload=lambda **kwargs: ["normalized"],
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            memory = root / ".manageroo" / "PROJECT-MEMORY.md"
            artifact = root / "run" / "artifacts" / "evidence.txt"
            memory.parent.mkdir(parents=True)
            artifact.parent.mkdir(parents=True)
            memory.write_text("portable project memory\n", encoding="utf-8")
            artifact.write_text("portable run artifact\n", encoding="utf-8")

            with patch.object(
                evidence_hardening,
                "_descriptor_traversal_supported",
                return_value=False,
            ):
                evidence_hardening.install_evidence_hardening(isolated_evidence)
                self.assertEqual(
                    PortableProjectMemoryProvider(root).retrieve("project memory"),
                    [],
                )
                self.assertEqual(
                    PortableRunArtifactProvider(root / "run").retrieve("run artifact"),
                    [],
                )

    def test_project_memory_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            outside = root / "outside.md"
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir(parents=True)
            outside.write_text("secret database migration", encoding="utf-8")
            try:
                memory.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            self.assertEqual(ProjectMemoryEvidenceProvider(repo).retrieve("database migration"), [])

    def test_project_memory_rejects_hard_link_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            outside = root / "outside.md"
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir(parents=True)
            outside.write_text("secret database migration", encoding="utf-8")
            try:
                os.link(outside, memory)
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")
            self.assertEqual(
                ProjectMemoryEvidenceProvider(repo).retrieve("database migration"),
                [],
            )

    def test_project_memory_parent_swap_cannot_redirect_descriptor_read(self):
        if not evidence_hardening._descriptor_traversal_supported():
            self.skipTest("descriptor-relative traversal unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            project_dir = repo / ".manageroo"
            moved_dir = repo / "original-manageroo"
            outside_dir = root / "outside"
            project_dir.mkdir(parents=True)
            outside_dir.mkdir()
            (project_dir / "PROJECT-MEMORY.md").write_text(
                "trusted project memory\n",
                encoding="utf-8",
            )
            (outside_dir / "PROJECT-MEMORY.md").write_text(
                "secret outside migration\n",
                encoding="utf-8",
            )
            original_reader = evidence_hardening._verified_bounded_text
            swapped = False

            def swap_then_read(*args, **kwargs):
                nonlocal swapped
                if not swapped:
                    project_dir.rename(moved_dir)
                    project_dir.symlink_to(outside_dir, target_is_directory=True)
                    swapped = True
                return original_reader(*args, **kwargs)

            try:
                with patch.object(
                    evidence_hardening,
                    "_verified_bounded_text",
                    side_effect=swap_then_read,
                ):
                    items = ProjectMemoryEvidenceProvider(repo).retrieve("outside migration")
            except OSError as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")

            self.assertTrue(swapped)
            self.assertEqual(items, [])

    def test_project_memory_never_scans_beyond_bounded_input_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir(parents=True)
            memory.write_bytes(b"x" * MAX_EVIDENCE_INPUT_BYTES + b"\nneedle-beyond-boundary\n")
            items = ProjectMemoryEvidenceProvider(repo).retrieve("needle-beyond-boundary")
            self.assertEqual(items, [])

    def test_run_artifact_never_scans_beyond_bounded_input_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp) / "run"
            artifact = run_root / "artifacts" / "large.txt"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"x" * MAX_EVIDENCE_INPUT_BYTES + b"\nneedle-beyond-boundary\n")
            items = RunArtifactEvidenceProvider(run_root).retrieve("needle-beyond-boundary")
            self.assertEqual(items, [])

    def test_run_artifact_rejects_hard_link_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_root = root / "run"
            outside = root / "outside.txt"
            artifact = run_root / "artifacts" / "leak.txt"
            artifact.parent.mkdir(parents=True)
            outside.write_text("secret artifact evidence", encoding="utf-8")
            try:
                os.link(outside, artifact)
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")
            self.assertEqual(
                RunArtifactEvidenceProvider(run_root).retrieve("artifact evidence"),
                [],
            )

    def test_run_artifact_root_swap_cannot_redirect_descriptor_walk(self):
        if not evidence_hardening._descriptor_traversal_supported():
            self.skipTest("descriptor-relative traversal unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_root = root / "run"
            artifact_root = run_root / "artifacts"
            moved_root = run_root / "original-artifacts"
            outside_root = root / "outside"
            artifact_root.mkdir(parents=True)
            outside_root.mkdir()
            (artifact_root / "inside.txt").write_text("trusted artifact\n", encoding="utf-8")
            (outside_root / "leak.txt").write_text(
                "secret outside artifact evidence\n",
                encoding="utf-8",
            )
            original_names = evidence_hardening._descriptor_names
            swapped = False

            def swap_then_list(directory_fd):
                nonlocal swapped
                if not swapped:
                    artifact_root.rename(moved_root)
                    artifact_root.symlink_to(outside_root, target_is_directory=True)
                    swapped = True
                return original_names(directory_fd)

            try:
                with patch.object(
                    evidence_hardening,
                    "_descriptor_names",
                    side_effect=swap_then_list,
                ):
                    items = RunArtifactEvidenceProvider(run_root).retrieve("outside evidence")
            except OSError as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")

            self.assertTrue(swapped)
            self.assertEqual(items, [])

    def test_context_compiler_includes_ranked_evidence_with_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, compiler = self._compiler(root)
            evidence = EvidenceItem(
                content="Current graph says a.txt feeds the worker.",
                source="gitnexus-query",
                location="a.txt",
                authority="current_repo",
                confidence=0.95,
                freshness=1.0,
            )
            packet = compiler.compile(
                "001",
                instructions="Do the bounded task.",
                requests=[ContextRequest("a.txt", "required", required=True)],
                evidence=[evidence],
            )
            prompt = (packet / "prompt.md").read_text(encoding="utf-8")
            manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("# Retrieved evidence", prompt)
            self.assertIn("gitnexus-query", prompt)
            self.assertIn("Retrieved evidence is context, not controller truth", prompt)
            self.assertEqual(manifest["evidence"][0]["content_sha256"], evidence.content_sha256)
            self.assertEqual(manifest["evidence"][0]["authority"], "current_repo")

    def test_context_compiler_accepts_controller_selected_evidence_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, compiler = self._compiler(root)
            evidence = EvidenceItem(
                content="The current repository graph owns this dependency.",
                source="gitnexus-query",
                location="src/core.py",
                authority="current_repo",
                confidence=0.93,
                freshness=1.0,
            )
            packet = compiler.compile(
                "002",
                instructions="Plan using bounded evidence.",
                requests=[ContextRequest("a.txt", "required", required=True)],
                metadata={
                    "role": "plan-compiler",
                    "_evidence_items": [evidence.to_dict()],
                    "_evidence_policy": {"context_only": True, "controller_authority": True},
                },
            )
            prompt = (packet / "prompt.md").read_text(encoding="utf-8")
            manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("The current repository graph owns this dependency.", prompt)
            self.assertEqual(manifest["evidence"][0]["source"], "gitnexus-query")
            self.assertEqual(manifest["evidence"][0]["location"], "src/core.py")


if __name__ == "__main__":
    unittest.main()
