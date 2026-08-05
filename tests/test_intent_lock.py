import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

from manageroo.cli import main
from manageroo.errors import ConfigurationError
from manageroo.intent_lock import audit_compaction_text, capture_intent_lock, format_compaction_audit, intent_lock_path, read_intent_lock, save_compaction_checkpoint
from manageroo.util import atomic_write_json, sha256_bytes, sha256_file

ROOT = Path(__file__).resolve().parents[1]


class IntentLockTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "product"; repo.mkdir(); subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True); (repo / "README.md").write_text("# Product\n", encoding="utf-8"); return repo.resolve()

    def test_capture_writes_machine_and_human_intent_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = capture_intent_lock(repo, want="Build the release helper without pretending it deploys.", outcomes=["Writes a release handoff"], must_not=["Do not deploy production"], proof=["release-ready reports READY"], corrections=["The command name is manageroo"], rejected=["Do not add GitHub Actions"], questions=["Which deployment target should the operator use?"], scopes=["Only this Git repo"], source="operator-chat")
            self.assertTrue(result["ok"]); lock = intent_lock_path(repo); self.assertTrue(lock.is_file()); payload = json.loads(lock.read_text(encoding="utf-8")); self.assertEqual(payload["want"], "Build the release helper without pretending it deploys."); self.assertIn("Do not deploy production", payload["must_not"]); self.assertIn("Do not add GitHub Actions", payload["rejected"]); markdown = lock.with_suffix(".md").read_text(encoding="utf-8"); self.assertIn("## Must Not Happen", markdown); self.assertIn("Do not deploy production", markdown); self.assertIn("## Rejected Ideas", markdown)

    def test_next_commands_shell_quote_repository_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo's; touch injected"
            root.mkdir()
            repo = self._repo(root)
            commands = [read_intent_lock(repo)["next_command"]]
            commands.append(capture_intent_lock(repo, want="Build it.")["next_command"])
            intent_lock_path(repo).write_text("[]", encoding="utf-8")
            commands.append(read_intent_lock(repo)["next_command"])
            capture_intent_lock(repo, want="Build it.", force=True)
            commands.append(audit_compaction_text(repo, "")["next_command"])
            commands.append(audit_compaction_text(repo, "Build it.")["next_command"])
            capture_intent_lock(
                repo,
                want="Ship it.",
                proof=["The release gate has not run."],
                force=True,
            )
            confidence_report = audit_compaction_text(
                repo,
                "Ship it. The release gate has not run. Production-ready.",
            )
            commands.append(confidence_report["next_command"])

            for command in commands:
                with self.subTest(command=command):
                    self.assertEqual(shlex.split(command).count(str(repo)), 1)

    def test_concurrent_capture_allows_exactly_one_non_force_writer(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            first_write_started = threading.Event()
            release_first_write = threading.Event()
            second_completed = threading.Event()
            results: dict[str, object] = {}

            def delayed_json_write(path, payload):
                if payload["want"] == "First intent wins.":
                    first_write_started.set()
                    if not release_first_write.wait(timeout=5):
                        raise TimeoutError("test did not release first intent write")
                atomic_write_json(path, payload)

            def capture(name: str, want: str) -> None:
                try:
                    results[name] = capture_intent_lock(repo, want=want)
                except BaseException as exc:
                    results[name] = exc
                finally:
                    if name == "second":
                        second_completed.set()

            with mock.patch("manageroo.intent_lock.atomic_write_json", side_effect=delayed_json_write):
                first = threading.Thread(target=capture, args=("first", "First intent wins."))
                second = threading.Thread(target=capture, args=("second", "Second intent loses."))
                first.start()
                self.assertTrue(first_write_started.wait(timeout=5))
                second.start()
                self.assertFalse(second_completed.wait(timeout=0.2))
                release_first_write.set()
                first.join(timeout=5)
                second.join(timeout=5)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertIsInstance(results["first"], dict)
            self.assertIsInstance(results["second"], ConfigurationError)
            lock = intent_lock_path(repo)
            self.assertEqual(json.loads(lock.read_text(encoding="utf-8"))["want"], "First intent wins.")
            markdown = lock.with_suffix(".md").read_text(encoding="utf-8")
            self.assertIn("First intent wins.", markdown)
            self.assertNotIn("Second intent loses.", markdown)

    def test_read_stays_consistent_during_forced_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(repo, want="Original intent.")
            lock = intent_lock_path(repo)
            snapshot_read = threading.Event()
            replacement_done = threading.Event()
            result: dict[str, object] = {}
            original_open = Path.open

            @contextmanager
            def delayed_open(path, *args, **kwargs):
                with original_open(path, *args, **kwargs) as handle:
                    yield handle
                if (
                    path == lock
                    and threading.current_thread().name == "intent-lock-reader"
                    and not snapshot_read.is_set()
                ):
                    snapshot_read.set()
                    if not replacement_done.wait(timeout=5):
                        raise TimeoutError("test did not replace the intent lock")

            def read_lock() -> None:
                try:
                    result["report"] = read_intent_lock(repo)
                except BaseException as exc:
                    result["error"] = exc

            with mock.patch.object(Path, "open", delayed_open):
                reader = threading.Thread(target=read_lock, name="intent-lock-reader")
                reader.start()
                self.assertTrue(snapshot_read.wait(timeout=5))
                capture_intent_lock(repo, want="Replacement intent.", force=True)
                replacement_done.set()
                reader.join(timeout=5)

            self.assertFalse(reader.is_alive())
            self.assertNotIn("error", result)
            report = result["report"]
            self.assertIsInstance(report, dict)
            serialized = json.dumps(
                report["lock"], indent=2, sort_keys=True, ensure_ascii=False
            ) + "\n"
            self.assertEqual(report["lock_hash"], sha256_bytes(serialized.encode("utf-8")))

    def test_capture_stays_consistent_during_competing_forced_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(repo, want="Initial intent.")
            lock = intent_lock_path(repo)
            snapshot_started = threading.Event()
            release_snapshot = threading.Event()
            results: dict[str, object] = {}
            original_open = Path.open

            def delayed_open(path, *args, **kwargs):
                if (
                    path == lock
                    and threading.current_thread().name == "first-force-capture"
                    and not snapshot_started.is_set()
                ):
                    snapshot_started.set()
                    if not release_snapshot.wait(timeout=5):
                        raise TimeoutError("test did not release the first capture")
                return original_open(path, *args, **kwargs)

            def capture(name: str, want: str) -> None:
                try:
                    results[name] = capture_intent_lock(repo, want=want, force=True)
                except BaseException as exc:
                    results[name] = exc

            with mock.patch.object(Path, "open", delayed_open):
                first = threading.Thread(
                    target=capture,
                    args=("first", "First replacement."),
                    name="first-force-capture",
                )
                second = threading.Thread(
                    target=capture,
                    args=("second", "Second replacement."),
                    name="second-force-capture",
                )
                first.start()
                self.assertTrue(snapshot_started.wait(timeout=5))
                second.start()
                second.join(timeout=0.2)
                release_snapshot.set()
                first.join(timeout=5)
                second.join(timeout=5)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            for name in ("first", "second"):
                with self.subTest(capture=name):
                    report = results[name]
                    self.assertIsInstance(report, dict)
                    serialized = json.dumps(
                        report["lock"], indent=2, sort_keys=True, ensure_ascii=False
                    ) + "\n"
                    self.assertEqual(
                        report["lock_hash"], sha256_bytes(serialized.encode("utf-8"))
                    )

    def test_failed_initial_capture_can_be_retried_without_force(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            lock = intent_lock_path(repo)

            with mock.patch(
                "manageroo.intent_lock.atomic_write_text",
                side_effect=OSError("simulated Markdown staging failure"),
            ):
                with self.assertRaisesRegex(OSError, "Markdown staging failure"):
                    capture_intent_lock(repo, want="Failed intent.")

            self.assertFalse(lock.exists())
            self.assertFalse(lock.with_suffix(".md").exists())
            result = capture_intent_lock(repo, want="Retry succeeds.")
            self.assertTrue(result["ok"])
            self.assertEqual(json.loads(lock.read_text(encoding="utf-8"))["want"], "Retry succeeds.")

    def test_failed_forced_capture_preserves_existing_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(repo, want="Original intent.")
            lock = intent_lock_path(repo)
            markdown = lock.with_suffix(".md")
            original_json = lock.read_bytes()
            original_markdown = markdown.read_bytes()

            with mock.patch(
                "manageroo.intent_lock.atomic_write_text",
                side_effect=OSError("simulated Markdown staging failure"),
            ):
                with self.assertRaisesRegex(OSError, "Markdown staging failure"):
                    capture_intent_lock(repo, want="Replacement intent.", force=True)

            self.assertEqual(lock.read_bytes(), original_json)
            self.assertEqual(markdown.read_bytes(), original_markdown)

    def test_failed_second_publication_rolls_back_first_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(repo, want="Original intent.")
            lock = intent_lock_path(repo)
            markdown = lock.with_suffix(".md")
            original_json = lock.read_bytes()
            original_markdown = markdown.read_bytes()
            original_replace = os.replace

            def fail_markdown_publication(source, destination):
                if Path(source).name == markdown.name and Path(destination) == markdown:
                    raise OSError("simulated Markdown publication failure")
                return original_replace(source, destination)

            with mock.patch(
                "manageroo.intent_lock.os.replace",
                side_effect=fail_markdown_publication,
            ):
                with self.assertRaisesRegex(OSError, "Markdown publication failure"):
                    capture_intent_lock(repo, want="Replacement intent.", force=True)

            self.assertEqual(lock.read_bytes(), original_json)
            self.assertEqual(markdown.read_bytes(), original_markdown)

    def test_interrupted_publication_regenerates_markdown_on_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(repo, want="Original intent.")
            lock = intent_lock_path(repo)
            markdown = lock.with_suffix(".md")
            original_markdown = markdown.read_bytes()
            script = """
import os
import sys
from pathlib import Path

import manageroo.intent_lock as intent_lock

repo = Path(sys.argv[1])
lock = intent_lock.intent_lock_path(repo)
real_replace = os.replace

def crash_after_json_publication(source, destination):
    result = real_replace(source, destination)
    if Path(destination) == lock and Path(source).parent.name.startswith(".intent-lock-"):
        os._exit(91)
    return result

intent_lock.os.replace = crash_after_json_publication
intent_lock.capture_intent_lock(repo, want="Replacement intent.", force=True)
"""
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join(
                filter(None, (str(ROOT / "src"), environment.get("PYTHONPATH", "")))
            )

            interrupted = subprocess.run(
                [sys.executable, "-c", script, str(repo)],
                env=environment,
                check=False,
            )

            self.assertEqual(interrupted.returncode, 91)
            self.assertEqual(
                json.loads(lock.read_text(encoding="utf-8"))["want"],
                "Replacement intent.",
            )
            self.assertEqual(markdown.read_bytes(), original_markdown)
            report = read_intent_lock(repo)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["lock"]["want"], "Replacement intent.")
            repaired_markdown = markdown.read_text(encoding="utf-8")
            self.assertIn("Replacement intent.", repaired_markdown)
            self.assertTrue(
                repaired_markdown.startswith(
                    f"<!-- manageroo-intent-lock-json-sha256: {report['lock_hash']} -->\n"
                )
            )

    def test_agent_surfaces_use_the_validating_intent_reader(self):
        surfaces = (
            ROOT / "src/manageroo/project.py",
            ROOT / "src/manageroo/assets/skills/uncle-matts-project-manageroo/SKILL.md",
        )
        for path in surfaces:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("manageroo intent show --json", text)
                self.assertIn(
                    "generated `INTENT-LOCK.md` directly",
                    " ".join(text.split()),
                )

    def test_audit_blocks_when_compaction_drops_must_not_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp)); capture_intent_lock(repo, want="Build the release helper.", must_not=["Do not deploy production"], rejected=["Do not add GitHub Actions"], proof=["release-ready reports READY"], scopes=["Only this Git repo"])
            report = audit_compaction_text(repo, "Current task: build the release helper. Proof: release-ready reports READY.")
            self.assertFalse(report["ok"]); self.assertEqual(report["status"], "blocked"); missing = {(item["category"], item["text"]) for item in report["missing"]}; self.assertIn(("must_not", "Do not deploy production"), missing); self.assertIn(("rejected", "Do not add GitHub Actions"), missing)

    def test_malformed_intent_locks_are_blocked_configuration_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(repo, want="Build the release helper.")
            path = intent_lock_path(repo)
            valid = json.loads(path.read_text(encoding="utf-8"))
            invalid_payloads = (
                ([], "top-level value must be a JSON object"),
                (None, "top-level value must be a JSON object"),
                ({**valid, "schema_version": 2}, "schema_version must be the integer 1"),
                ({**valid, "created_at": 7}, "created_at must be a string"),
                ({**valid, "outcomes": "one outcome"}, "outcomes must be a list of strings"),
                ({**valid, "outcomes": ["valid", 7]}, "outcomes[1] must be a string"),
                ({**valid, "audit_policy": None}, "audit_policy must be a JSON object"),
                (
                    {
                        **valid,
                        "audit_policy": {
                            **valid["audit_policy"],
                            "strict_phrase_preservation": "yes",
                        },
                    },
                    "audit_policy.strict_phrase_preservation must be a boolean",
                ),
                (
                    {
                        **valid,
                        "audit_policy": {
                            **valid["audit_policy"],
                            "required_categories": "want",
                        },
                    },
                    "audit_policy.required_categories must be a list of strings",
                ),
            )

            for payload, detail in invalid_payloads:
                with self.subTest(detail=detail):
                    path.write_text(json.dumps(payload), encoding="utf-8")

                    lock_report = read_intent_lock(repo)
                    audit_report = audit_compaction_text(repo, "Build the release helper.")

                    error = f"INTENT-LOCK.json is invalid: {detail}"
                    self.assertFalse(lock_report["ok"])
                    self.assertEqual(lock_report["error"], error)
                    self.assertFalse(audit_report["ok"])
                    self.assertEqual(audit_report["status"], "blocked")
                    self.assertEqual(
                        audit_report["missing"],
                        [{"category": "intent_lock", "text": error}],
                    )

    def test_corrupt_intent_locks_are_blocked_configuration_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(repo, want="Build the release helper.")
            path = intent_lock_path(repo)
            corruptions = (
                (b"{", "malformed JSON at line 1 column 2"),
                (b"\xff", "file must contain UTF-8 encoded JSON"),
            )

            for content, detail in corruptions:
                with self.subTest(detail=detail):
                    path.write_bytes(content)

                    lock_report = read_intent_lock(repo)
                    audit_report = audit_compaction_text(repo, "Build the release helper.")

                    self.assertFalse(lock_report["ok"])
                    self.assertIn(detail, lock_report["error"])
                    self.assertIn("--force", lock_report["next_command"])
                    self.assertFalse(audit_report["ok"])
                    self.assertEqual(audit_report["status"], "blocked")
                    self.assertEqual(
                        audit_report["missing"],
                        [{"category": "intent_lock", "text": lock_report["error"]}],
                    )
                    self.assertEqual(audit_report["next_command"], lock_report["next_command"])

    def test_audit_passes_when_pinned_truth_survives(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp)); capture_intent_lock(repo, want="Build the release helper.", outcomes=["Writes a release handoff"], must_not=["Do not deploy production"], proof=["release-ready reports READY"], corrections=["The command name is manageroo"])
            report = audit_compaction_text(repo, "\n".join(["Intent: Build the release helper.", "Outcome: Writes a release handoff.", "Must not: Do not deploy production.", "Proof: release-ready reports READY.", "Correction: The command name is manageroo."]))
            self.assertTrue(report["ok"], report); self.assertEqual(report["status"], "passed"); self.assertFalse(report["missing"])

    def test_audit_allows_confidence_claim_supported_by_locked_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp)); capture_intent_lock(repo, want="Ship the release.", proof=["Production-ready because the release gate and smoke tests passed."])
            report = audit_compaction_text(repo, "\n".join(["Intent: Ship the release.", "Proof: Production-ready because the release gate and smoke tests passed."]))
            self.assertTrue(report["ok"], report); self.assertEqual(report["status"], "passed"); self.assertFalse(report["confidence_claims_blocking"]); self.assertTrue(report["warnings"])

    def test_audit_blocks_confidence_claim_without_matching_locked_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp)); capture_intent_lock(repo, want="Ship the release.", proof=["The release gate and smoke tests have not run."])
            report = audit_compaction_text(repo, "\n".join(["Intent: Ship the release.", "Proof: The release gate and smoke tests have not run.", "Status: Production-ready."]))
            self.assertFalse(report["ok"]); self.assertEqual(report["status"], "blocked"); self.assertTrue(report["confidence_claims_blocking"]); self.assertFalse(report["missing"])

    def test_audit_does_not_treat_word_apostrophes_as_quote_delimiters(self):
        summaries = (
            "Intent: Ship the release.\nStatus: It's production-ready.",
            "Intent: Ship the release.\nManageroo's result is production-ready.",
        )
        for summary in summaries:
            with self.subTest(summary=summary), tempfile.TemporaryDirectory() as temp:
                repo = self._repo(Path(temp))
                capture_intent_lock(repo, want="Ship the release.")

                report = audit_compaction_text(repo, summary)

                self.assertFalse(report["ok"], report)
                self.assertEqual(report["status"], "blocked")
                self.assertTrue(report["confidence_claims_blocking"])
                self.assertEqual(
                    [warning["text"] for warning in report["warnings"]],
                    ["production-ready"],
                )

    def test_audit_ignores_negated_or_quoted_confidence_terms_in_summary(self):
        summaries = (
            "Intent: Ship the release.\nStatus: not production-ready.",
            "Intent: Ship the release.\nThe release is not, in fact, production-ready.",
            "Intent: Ship the release.\nThe release is not — in fact — production-ready.",
            "Intent: Ship the release.\nThe release isn't remotely production-ready.",
            "Intent: Ship the release.\nThe docs say 'production-ready' is prohibited.",
            'Intent: Ship the release.\nDo not describe this as "production-ready".',
            "Intent: Ship the release.\nDo not describe the build as production-ready.",
            "Intent: Ship the release.\nWe cannot claim production-ready.",
        )
        for summary in summaries:
            with self.subTest(summary=summary), tempfile.TemporaryDirectory() as temp:
                repo = self._repo(Path(temp))
                capture_intent_lock(repo, want="Ship the release.")

                report = audit_compaction_text(repo, summary)

                self.assertTrue(report["ok"], report)
                self.assertEqual(report["status"], "passed")
                self.assertFalse(report["confidence_claims_blocking"])
                self.assertFalse(report["warnings"])

    def test_audit_blocks_affirmative_claim_after_separate_negated_clause(self):
        summaries = (
            "Checks did not run, but the release is production-ready.",
            "Checks did not run, the release is production-ready.",
            "Although checks did not run, the release is production-ready.",
            "Checks did not run, release is production-ready.",
            "Checks did not run, the current desktop release candidate is production-ready.",
            "Checks did not run, production-ready.",
            "Checks did not run, I call the release production-ready.",
            "Checks did not run, we consider the release production-ready.",
            "Checks did not run and the release is production-ready.",
            "Checks did not run and reviewers declared the release production-ready.",
            "Checks did not run while the release is production-ready.",
            "Checks did not run while reviewers say the release is production-ready.",
            "Checks did not run whereas the release is production-ready.",
            "Checks did not run — the release is production-ready.",
            "The release was not tested and is production-ready.",
            "Checks did not run because the release is production-ready.",
            "Tests did not run since the release is production-ready.",
            "Tests did not run when reviewers declared the release production-ready.",
            "Tests did not run before reviewers declared the release production-ready.",
            "Without running tests reviewers declared the release production-ready.",
            "Tests did not run so reviewers called the release production-ready.",
            "Do not claim checks passed, but the release is production-ready.",
            "Do not claim checks passed yet reviewers declare the release production-ready.",
            "Do not say tests ran nonetheless reviewers call it production-ready.",
            "We should not say checks passed nevertheless the release is production-ready.",
            "Checks didn't run, but the release is production-ready.",
            "Tests weren't run, yet reviewers call the release production-ready.",
            "We couldn't verify artifacts although the build is production-ready.",
        )
        for summary in summaries:
            with self.subTest(summary=summary), tempfile.TemporaryDirectory() as temp:
                repo = self._repo(Path(temp))
                capture_intent_lock(repo, want="Ship the release.")

                report = audit_compaction_text(
                    repo,
                    f"Intent: Ship the release.\n{summary}",
                )

                self.assertFalse(report["ok"], report)
                self.assertEqual(report["status"], "blocked")
                self.assertTrue(report["confidence_claims_blocking"])
                self.assertEqual(
                    [warning["text"] for warning in report["warnings"]],
                    ["production-ready"],
                )

    def test_audit_rejects_negated_or_quoted_confidence_claims_as_proof(self):
        cases = (
            "We cannot claim production-ready because the release gate has not run.",
            'The documentation uses "production-ready" only as an example label.',
            "Production-ready is not proven by the current evidence.",
            "Production-ready.",
            "Production-ready because no checks passed.",
            "Production-ready because smoke tests weren't successful.",
            "Production-ready because release gates haven't passed.",
            "Production-ready because the build hasn't been verified.",
            "Production-ready because the result wasn't confirmed.",
            "Production-ready because every verification gate failed.",
            "Production-ready after tests fail.",
            'The document says "apparently production-ready and verified".',
            'The report says "production-ready because every gate passed',
            "Production-ready remains pending although an unrelated unit test passed.",
        )
        for proof in cases:
            with self.subTest(proof=proof), tempfile.TemporaryDirectory() as temp:
                repo = self._repo(Path(temp))
                capture_intent_lock(repo, want="Ship the release.", proof=[proof])
                report = audit_compaction_text(
                    repo,
                    f"Intent: Ship the release.\nProof: {proof}\nStatus: Production-ready.",
                )
                self.assertFalse(report["ok"], report)
                self.assertTrue(report["confidence_claims_blocking"])

    def test_audit_allows_success_with_explicitly_zero_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            proof = "Production-ready after all release gates passed with no failures."
            capture_intent_lock(repo, want="Ship the release.", proof=[proof])

            report = audit_compaction_text(
                repo,
                f"Intent: Ship the release.\nProof: {proof}",
            )

            self.assertTrue(report["ok"], report)
            self.assertFalse(report["confidence_claims_blocking"])

    def test_audit_allows_successful_outcome_before_claim(self):
        proofs = (
            "All release gates passed, therefore production-ready.",
            "All checks passed. The build is production-ready.",
        )
        for proof in proofs:
            with self.subTest(proof=proof), tempfile.TemporaryDirectory() as temp:
                repo = self._repo(Path(temp))
                capture_intent_lock(repo, want="Ship the release.", proof=[proof])

                report = audit_compaction_text(
                    repo,
                    f"Intent: Ship the release.\nProof: {proof}",
                )

                self.assertTrue(report["ok"], report)
                self.assertFalse(report["confidence_claims_blocking"])

    def test_audit_rejects_unrelated_success_as_completion_proof(self):
        proofs = (
            "Production-ready because an unrelated unit test passed.",
            "An unrelated unit test passed, therefore production-ready.",
            "An unrelated unit test passed. The build is production-ready.",
        )
        for proof in proofs:
            with self.subTest(proof=proof), tempfile.TemporaryDirectory() as temp:
                repo = self._repo(Path(temp))
                capture_intent_lock(repo, want="Ship the release.", proof=[proof])

                report = audit_compaction_text(
                    repo,
                    f"Intent: Ship the release.\nProof: {proof}",
                )

                self.assertFalse(report["ok"], report)
                self.assertTrue(report["confidence_claims_blocking"])

    def test_audit_rejects_conflicting_outcome_after_confidence_claim(self):
        proofs = (
            "All checks passed. Production-ready although deployment failed.",
            "All checks passed. The build is production-ready, but smoke tests failed.",
        )
        for proof in proofs:
            with self.subTest(proof=proof), tempfile.TemporaryDirectory() as temp:
                repo = self._repo(Path(temp))
                capture_intent_lock(repo, want="Ship the release.", proof=[proof])

                report = audit_compaction_text(
                    repo,
                    f"Intent: Ship the release.\nProof: {proof}",
                )

                self.assertFalse(report["ok"], report)
                self.assertTrue(report["confidence_claims_blocking"])

    def test_cli_capture_and_compact_audit_json(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp)); stdout = io.StringIO()
            with redirect_stdout(stdout): code = main(["intent", "capture", str(repo), "--want", "Build the release helper.", "--must-not", "Do not deploy production", "--proof", "release-ready reports READY", "--json"])
            self.assertEqual(code, 0); self.assertTrue(json.loads(stdout.getvalue())["ok"])
            summary = repo / "summary.md"; summary.write_text("Intent: Build the release helper.\nMust not: Do not deploy production.\nProof: release-ready reports READY.\n", encoding="utf-8"); stdout = io.StringIO()
            with redirect_stdout(stdout): code = main(["compact", "audit", str(repo), "--summary", str(summary), "--json"])
            payload = json.loads(stdout.getvalue()); self.assertEqual(code, 0); self.assertTrue(payload["ok"]); self.assertEqual(payload["summary_path"], str(summary.resolve()))

    def test_checkpoint_persists_the_same_summary_snapshot_that_was_audited(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(repo, want="Build the release helper.")
            summary = repo / "summary.md"
            original = "Intent: Build the release helper.\n"
            replacement = "Replacement written during checkpoint creation.\n"
            summary.write_text(original, encoding="utf-8")

            def mutate_source(repo_path, summary_text, *, summary_path=None):
                summary.write_text(replacement, encoding="utf-8")
                return audit_compaction_text(
                    repo_path,
                    summary_text,
                    summary_path=summary_path,
                )

            with mock.patch(
                "manageroo.intent_lock.audit_compaction_text",
                side_effect=mutate_source,
            ):
                report = save_compaction_checkpoint(repo, summary)

            checkpoint = Path(report["checkpoint_path"])
            checkpoint_audit = json.loads(
                Path(report["checkpoint_audit_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(summary.read_text(encoding="utf-8"), replacement)
            self.assertEqual(checkpoint.read_text(encoding="utf-8"), original)
            self.assertEqual(checkpoint_audit["summary_hash"], report["summary_hash"])
            self.assertEqual(checkpoint_audit["summary_hash"], sha256_file(checkpoint))

    def test_format_compaction_audit_is_plain_about_blockers(self):
        text = format_compaction_audit({"ok": False, "status": "blocked", "lock_path": "/repo/.manageroo/intent/INTENT-LOCK.json", "missing": [{"category": "must_not", "text": "Do not deploy production"}], "warnings": [{"code": "confidence_claim", "text": "perfect"}], "next_command": "manageroo intent show"})
        self.assertIn("COMPACTION AUDIT: BLOCKED", text); self.assertIn("MISSING must_not: Do not deploy production", text); self.assertIn("WARN confidence_claim: perfect", text); self.assertIn("Next: manageroo intent show", text)

    def test_public_docs_explain_intent_lock_and_compaction_audit(self):
        surfaces = {
            "README.md": [".manageroo/intent/INTENT-LOCK.md", "manageroo compact audit", "remain unproven until matching affirmative evidence exists and records a successful outcome"],
            "docs/CONTEXT_COMPILER.md": ["Chat compaction is not the source of truth", "strict phrase-preservation audit"],
            "docs/ENFORCEMENT_MATRIX.md": ["Compaction cannot drop must-not rules", "Intent lock plus compaction audit"],
            "docs/SOLO_OPERATOR_MODE.md": ["solo captures an intent lock", "compact audit"],
        }
        for relative, phrases in surfaces.items():
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            for phrase in phrases:
                with self.subTest(surface=relative, phrase=phrase): self.assertIn(phrase.lower(), text)


if __name__ == "__main__":
    unittest.main()
