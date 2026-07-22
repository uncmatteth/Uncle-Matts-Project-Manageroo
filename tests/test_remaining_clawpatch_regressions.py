from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from manageroo.acceptance import build_acceptance_evidence
from manageroo.adapters.base import AgentAdapter, AgentRequest
from manageroo.adapters.budget import BudgetedAdapter
from manageroo.adapters.pool import WorkerPoolAdapter
from manageroo.context import ContextCompiler, ContextRequest
from manageroo.errors import AgentExecutionError, ContextBudgetError, SafetyError, ValidationError
from manageroo.evidence import _read_bounded_text, normalize_external_payload
from manageroo.ideas import IdeaInbox
from manageroo.install_status import uninstall_plan
from manageroo.policy import ScopePolicy, validate_allowed_scope_patterns
from manageroo.projects import selected_project_command
from manageroo.schema import extract_json
from manageroo.token_modes import install_core_helper_skills, read_token_mode, set_token_mode
from manageroo.util import read_json


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_RELEASE_SPEC = importlib.util.spec_from_file_location(
    "manageroo_package_release_regression", ROOT / "scripts" / "package_release.py"
)
assert PACKAGE_RELEASE_SPEC and PACKAGE_RELEASE_SPEC.loader
package_release = importlib.util.module_from_spec(PACKAGE_RELEASE_SPEC)
PACKAGE_RELEASE_SPEC.loader.exec_module(package_release)


class _FailingWorker(AgentAdapter):
    def __init__(self):
        self.calls = 0

    def doctor(self, cwd: Path) -> dict:
        return {"ok": True}

    def run(self, request: AgentRequest):
        self.calls += 1
        raise AgentExecutionError("expected failure")


class RemainingClawpatchRegressions(unittest.TestCase):
    def test_author_documentation_does_not_require_authentication_demo(self):
        outcome = "Update author documentation"
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": [outcome]},
            gate_results=[{"gate": {"id": "docs"}, "result": {"exit_code": 0}}],
            demonstration={
                "gates": [],
                "product_evidence": [{"outcome": outcome, "gate_ids": ["docs"]}],
            },
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "passed")

    def test_root_level_secret_and_credential_paths_are_forbidden(self):
        for path in ("client-secret.json", "credentials.toml", "config/client-secret.json", "config/credentials.toml"):
            with self.subTest(path=path), self.assertRaises(SafetyError):
                validate_allowed_scope_patterns([path])
        policy = ScopePolicy(allowed=("client-secret.json",))
        with self.assertRaises(SafetyError):
            policy.validate_paths(["client-secret.json"])

    def test_invalid_numeric_project_selection_is_not_reinterpreted_as_path(self):
        report = {"projects": [{"path": "/tmp/project", "next_command": "manageroo next /tmp/project"}]}
        for answer in ("0", "2", "99"):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                selected_project_command(report, answer)

    def test_strict_json_rejects_nonfinite_numbers(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token), self.assertRaises(ValidationError):
                extract_json(f'{{"score": {token}}}')
            with self.subTest(embedded=token), self.assertRaises(ValidationError):
                extract_json(f"prefix {{\"score\": {token}}} suffix")

    def test_empty_structured_evidence_is_not_fabricated_as_text(self):
        self.assertEqual(normalize_external_payload(provider="x", payload="[]"), [])
        self.assertEqual(normalize_external_payload(provider="x", payload='{"items":[]}'), [])
        prose = normalize_external_payload(provider="x", payload="plain evidence")
        self.assertEqual(len(prose), 1)
        self.assertEqual(prose[0].content, "plain evidence")

    def test_bounded_utf8_reader_keeps_valid_prefix_when_cut_splits_character(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unicode.txt"
            path.write_bytes(b"abc" + "é".encode("utf-8") + b"tail")
            result = _read_bounded_text(path, max_bytes=4)
            self.assertIsNotNone(result)
            text, _mtime = result
            self.assertEqual(text, "abc")

    def test_context_manifest_records_exact_source_hash_and_same_size_mutation_is_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            source = repo / "a.txt"
            source.write_text("alpha\n", encoding="utf-8")
            compiler = ContextCompiler(
                repo,
                root / "packets",
                max_input_tokens=500,
                reserve_output_tokens=20,
                chars_per_token=1.0,
                max_single_file_tokens=100,
            )
            packet = compiler.compile(
                "p",
                instructions="inspect",
                requests=[ContextRequest("a.txt", "proof", required=True)],
            )
            manifest = read_json(packet / "manifest.json")
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(manifest["entries"][0]["source_sha256"], expected)
            self.assertRegex(manifest["entries"][0]["source_sha256"], r"^[0-9a-f]{64}$")
            source.write_text("bravo\n", encoding="utf-8")
            with self.assertRaises(SafetyError):
                compiler.validate_freshness(manifest)

    def test_failed_context_compile_does_not_reserve_packet_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            compiler = ContextCompiler(
                repo,
                root / "packets",
                max_input_tokens=500,
                reserve_output_tokens=20,
                chars_per_token=1.0,
                max_single_file_tokens=100,
            )
            with self.assertRaises(ContextBudgetError):
                compiler.compile(
                    "retryable",
                    instructions="inspect",
                    requests=[ContextRequest("missing.txt", "proof", required=True)],
                )
            (repo / "missing.txt").write_text("now present\n", encoding="utf-8")
            packet = compiler.compile(
                "retryable",
                instructions="inspect",
                requests=[ContextRequest("missing.txt", "proof", required=True)],
            )
            self.assertTrue((packet / "manifest.json").is_file())

    def test_serialized_context_overhead_is_counted_in_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            requests = []
            for index in range(10):
                name = f"f{index}.txt"
                (repo / name).write_text("x", encoding="utf-8")
                requests.append(ContextRequest(name, "tiny", required=True))
            compiler = ContextCompiler(
                repo,
                root / "packets",
                max_input_tokens=350,
                reserve_output_tokens=20,
                chars_per_token=1.0,
                max_single_file_tokens=100,
            )
            with self.assertRaises(ContextBudgetError):
                compiler.compile("overhead", instructions="x", requests=requests)

    def test_worker_pool_fallback_cannot_exceed_shared_call_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = _FailingWorker()
            second = _FailingWorker()
            pool = WorkerPoolAdapter([("first", first), ("second", second)])
            adapter = BudgetedAdapter(
                pool,
                max_total_worker_calls=1,
                state_path=root / "budget.json",
            )
            request = AgentRequest(
                role="test",
                prompt_path=root / "prompt.md",
                schema_path=root / "schema.json",
                output_path=root / "out.json",
                cwd=root,
                sandbox="read-only",
                timeout_seconds=30,
            )
            with self.assertRaises(AgentExecutionError):
                adapter.run(request)
            self.assertEqual(first.calls, 1)
            self.assertEqual(second.calls, 0)
            self.assertEqual(read_json(root / "budget.json")["worker_calls_consumed"], 1)

    def test_concurrent_idea_claim_has_exactly_one_winner(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            first = IdeaInbox(repo)
            second = IdeaInbox(repo)
            first.add("one idea")
            barrier = threading.Barrier(2)

            def claim(inbox: IdeaInbox, run_id: str):
                barrier.wait()
                return inbox.attach_pending(run_id)

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda args: claim(*args), [(first, "run-a"), (second, "run-b")]))
            self.assertEqual(sum(len(items) for items in results), 1)
            stored = first.list()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["status"], "attached")
            self.assertIn(stored[0]["linked_run"], {"run-a", "run-b"})

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_bundled_skill_install_refuses_symlinked_skill_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skills = root / "skills"
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "SKILL.md"
            marker.write_text("original", encoding="utf-8")
            skills.mkdir()
            os.symlink(outside, skills / "pimp-my-prompt", target_is_directory=True)
            with self.assertRaises(ValueError):
                install_core_helper_skills(skills)
            self.assertEqual(marker.read_text(encoding="utf-8"), "original")

    def test_token_mode_failed_atomic_write_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "token-mode.json"
            state.write_text(json.dumps({"mode": "off"}) + "\n", encoding="utf-8")
            before = state.read_bytes()
            with patch("manageroo.token_modes.atomic_write_json", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    set_token_mode("caveman", state_path=state, install_skills=False)
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual(read_token_mode(state)["mode"], "off")

    def test_uninstall_plan_uses_only_recorded_owned_custom_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            custom = root / "custom" / "manageroo"
            custom.parent.mkdir(parents=True)
            custom.write_text(
                "#!/bin/sh\nexport MANAGEROO_PREFIX=/tmp/x\nexec python -m manageroo \"$@\"\n",
                encoding="utf-8",
            )
            prefix.mkdir()
            (prefix / "install-lock.json").write_text(
                json.dumps({"launcher": str(custom), "external_tools": []}),
                encoding="utf-8",
            )
            plan = uninstall_plan(prefix=prefix)
            self.assertIn(str(custom), plan["core_paths"])
            self.assertTrue(plan["launcher_ownership_known"])

    def test_sensitive_release_policy_rejects_tracked_secret_names_directly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixtures = [".env", "credentials.json", "id_rsa", "private.key", "service-account.json"]
            with patch.object(package_release, "ROOT", root):
                for name in fixtures:
                    path = root / name
                    path.write_text("secret", encoding="utf-8")
                    with self.subTest(name=name):
                        self.assertFalse(package_release.release_file_allowed(path))
                benign = root / "scratch.txt"
                benign.write_text("ok", encoding="utf-8")
                self.assertTrue(package_release.release_file_allowed(benign))


if __name__ == "__main__":
    unittest.main()
