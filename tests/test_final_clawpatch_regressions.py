import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.acceptance import _needs_demonstration, build_acceptance_evidence
from manageroo.chiptune import ThemePlayback
from manageroo.clawpatch_release import _run as run_clawpatch_process
from manageroo.evidence import ProjectMemoryEvidenceProvider, normalize_external_payload
from manageroo.gbrain_setup import gbrain_setup_status, summarize_sync_status
from manageroo.runner import CommandRunner
from manageroo.skill_pack import import_skill_folder, scan_skill_folder
from manageroo.stack_doctor import _safe_probe_record
from manageroo.truth_contract import claim_is_explicitly_denied, find_overclaim_offenders
from manageroo.util import redact_argv, redact_text


class _KilledProcess:
    def __init__(self):
        self.wait_calls = 0
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired(["player"], timeout or 0)
        return -9

    def kill(self):
        self.killed = True


class _Pipe:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _StubbornProcessGroup:
    def __init__(self):
        self.pid = 4321
        self.returncode = None
        self.stdout = _Pipe()
        self.stderr = _Pipe()
        self.stdin = None
        self.communicate_calls = 0
        self.wait_calls = []
        self.killed = False

    def communicate(self, input=None, timeout=None):
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(
                ["tool"], timeout or 0, output="initial output", stderr="initial error"
            )
        raise subprocess.TimeoutExpired(
            ["tool"], timeout or 0, output="initial output plus cleanup", stderr="cleanup error"
        )

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        raise subprocess.TimeoutExpired(["tool"], timeout or 0)

    def kill(self):
        self.killed = True


class _InterruptedProcessGroup:
    def __init__(self):
        self.pid = 4321
        self.returncode = -15
        self.stdout = _Pipe()
        self.stderr = _Pipe()
        self.stdin = None
        self.communicate_calls = 0

    def communicate(self, input=None, timeout=None):
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            raise KeyboardInterrupt
        return "cleanup output", "cleanup error"

    def kill(self):
        self.returncode = -9


class FinalClawpatchRegressionTests(unittest.TestCase):
    def test_compound_json_and_split_argv_secrets_are_redacted(self):
        payload = {
            "access_token": "alpha",
            "nested": {
                "github_token": "beta",
                "client_secret": "gamma",
                "database_password": "delta",
            },
        }
        redacted = redact_text(json.dumps(payload))
        for secret in ("alpha", "beta", "gamma", "delta"):
            self.assertNotIn(secret, redacted)
        argv = redact_argv(["tool", "--token", "abc123", "--password", "hunter2", "--api-key=xyz"])
        rendered = json.dumps(argv)
        for secret in ("abc123", "hunter2", "xyz"):
            self.assertNotIn(secret, rendered)

    def test_camel_case_json_secret_keys_are_redacted_recursively_and_in_argv(self):
        payload = {
            "accessToken": "access-value",
            "nested": {
                "refreshToken": "refresh-value",
                "items": [
                    {"apiKey": "api-value", "label": "visible"},
                    {"clientSecret": "client-value"},
                ],
            },
            "public": "keep-me",
        }
        expected = {
            "accessToken": "<REDACTED>",
            "nested": {
                "refreshToken": "<REDACTED>",
                "items": [
                    {"apiKey": "<REDACTED>", "label": "visible"},
                    {"clientSecret": "<REDACTED>"},
                ],
            },
            "public": "keep-me",
        }

        self.assertEqual(json.loads(redact_text(json.dumps(payload))), expected)
        self.assertEqual(json.loads(redact_argv([json.dumps(payload)])[0]), expected)

    def test_private_key_credentials_and_pem_blocks_are_redacted(self):
        pem = (
            "-----BEGIN PRIVATE KEY-----\n"
            "private-key-body\n"
            "-----END PRIVATE KEY-----"
        )
        payload = {
            "private_key": pem,
            "signingKey": "signing-value",
            "passwd": "password-value",
            "credential": "credential-value",
            "public_key": "public-value",
        }

        redacted_json = json.loads(redact_text(json.dumps(payload)))
        for key in ("private_key", "signingKey", "passwd", "credential"):
            self.assertEqual(redacted_json[key], "<REDACTED>")
        self.assertEqual(redacted_json["public_key"], "public-value")

        redacted_text = redact_text(f"before\n{pem}\nafter")
        self.assertEqual(redacted_text, "before\n<REDACTED>\nafter")
        self.assertNotIn("private-key-body", redacted_text)

        argv = redact_argv(
            [
                "tool",
                "--private-key",
                "split-value",
                "--signing-key=joined-value",
                "--passwd",
                "passwd-value",
                "--credential=credential-flag-value",
                "--public-key",
                "public-value",
            ]
        )
        self.assertEqual(
            argv,
            [
                "tool",
                "--private-key",
                "<REDACTED>",
                "--signing-key=<REDACTED>",
                "--passwd",
                "<REDACTED>",
                "--credential=<REDACTED>",
                "--public-key",
                "public-value",
            ],
        )

    def test_stack_doctor_probe_record_redacts_split_secret_arguments(self):
        record = _safe_probe_record(
            {
                "ok": False,
                "exit_code": 1,
                "argv": ["tool", "--token", "abc123", "--password", "hunter2"],
                "output": "authorization=secret-value",
            }
        )
        rendered = json.dumps(record)
        self.assertNotIn("abc123", rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("secret-value", rendered)

    def test_command_runner_preserves_timeout_byte_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            exc = subprocess.TimeoutExpired(["tool"], 1, output=b"partial stdout", stderr=b"partial stderr")
            with patch("manageroo.runner.subprocess.run", side_effect=exc):
                result = CommandRunner().run(
                    ["tool"],
                    cwd=Path(temp),
                    timeout_seconds=1,
                    kill_process_group=False,
                )
        self.assertTrue(result.timed_out)
        self.assertIn("partial stdout", result.stdout)
        self.assertIn("partial stderr", result.stderr)

    def test_command_runner_decodes_utf8_output_with_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            result = CommandRunner().run(
                [
                    sys.executable,
                    "-c",
                    "import os; os.write(1, b'before\\x8fafter\\n')",
                ],
                cwd=Path(temp),
                timeout_seconds=5,
            )

        self.assertTrue(result.passed)
        self.assertEqual(result.stdout, "before\ufffdafter\n")

    def test_clawpatch_process_reader_decodes_utf8_output_with_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_clawpatch_process(
                [
                    sys.executable,
                    "-c",
                    "import os; os.write(1, b'before\\x8fafter\\n')",
                ],
                cwd=Path(temp),
                timeout=5,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "before\ufffdafter\n")

    @unittest.skipIf(os.name == "nt", "POSIX process-group assertion")
    def test_command_runner_timeout_kills_the_default_child_process_group(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "orphan-ran.txt"
            child = (
                "import time; from pathlib import Path; "
                f"time.sleep(2); Path({str(marker)!r}).write_text('orphan', encoding='utf-8')"
            )
            parent = (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
            )
            result = CommandRunner().run(
                [sys.executable, "-c", parent],
                cwd=root,
                timeout_seconds=1,
            )
            self.assertTrue(result.timed_out)
            time.sleep(2)
            self.assertFalse(marker.exists())

    def test_windows_process_group_timeout_cleanup_has_no_unbounded_communicate(self):
        process = _StubbornProcessGroup()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch("manageroo.runner.os.name", "nt"),
                patch("manageroo.runner.subprocess.CREATE_NEW_PROCESS_GROUP", 512, create=True),
                patch("manageroo.runner.subprocess.Popen", return_value=process),
                patch("manageroo.runner.subprocess.run") as taskkill,
            ):
                result = CommandRunner().run(
                    ["tool"],
                    cwd=root,
                    timeout_seconds=1,
                    kill_process_group=True,
                )

        self.assertTrue(result.timed_out)
        self.assertEqual(process.communicate_calls, 2)
        self.assertEqual(process.wait_calls, [5])
        self.assertTrue(process.killed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)
        self.assertIn("cleanup", result.stdout)
        self.assertEqual(taskkill.call_args.kwargs["timeout"], 10)

    @unittest.skipIf(os.name == "nt", "POSIX process-group API")
    def test_posix_keyboard_interrupt_terminates_and_reaps_the_child_process_group(self):
        process = _InterruptedProcessGroup()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch("manageroo.runner.os.name", "posix"),
                patch("manageroo.runner.subprocess.Popen", return_value=process),
                patch("manageroo.runner.os.killpg") as killpg,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    CommandRunner().run(
                        ["tool"],
                        cwd=root,
                        timeout_seconds=900,
                        kill_process_group=True,
                    )

        killpg.assert_called_once_with(process.pid, signal.SIGTERM)
        self.assertEqual(process.communicate_calls, 2)

    @unittest.skipIf(os.name == "nt", "POSIX signal integration assertion")
    def test_real_keyboard_interrupt_does_not_leave_the_supervised_child_running(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "orphan-ran.txt"
            child = (
                "import time; from pathlib import Path; "
                f"time.sleep(2); Path({str(marker)!r}).write_text('orphan', encoding='utf-8')"
            )
            supervised = (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
            )
            harness = (
                "import sys; from pathlib import Path; "
                "from manageroo.runner import CommandRunner; "
                f"CommandRunner().run([sys.executable, '-c', {supervised!r}], "
                f"cwd=Path({str(root)!r}), timeout_seconds=900, kill_process_group=True)"
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path.cwd() / "src")
            controller = subprocess.Popen(
                [sys.executable, "-c", harness],
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(0.5)
            controller.send_signal(signal.SIGINT)
            controller.communicate(timeout=10)
            time.sleep(2)
            self.assertFalse(marker.exists())

    def test_windows_keyboard_interrupt_terminates_and_reaps_the_child_process_tree(self):
        process = _InterruptedProcessGroup()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch("manageroo.runner.os.name", "nt"),
                patch("manageroo.runner.subprocess.CREATE_NEW_PROCESS_GROUP", 512, create=True),
                patch("manageroo.runner.subprocess.Popen", return_value=process),
                patch("manageroo.runner.subprocess.run") as taskkill,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    CommandRunner().run(
                        ["tool"],
                        cwd=root,
                        timeout_seconds=900,
                        kill_process_group=True,
                    )

        self.assertEqual(
            taskkill.call_args.args[0],
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        )
        self.assertEqual(taskkill.call_args.kwargs["timeout"], 10)
        self.assertEqual(process.communicate_calls, 2)

    def test_truth_contract_checks_every_occurrence_and_prerequisite_negation(self):
        repeated = (
            "Manageroo does not provide full vision support, but Manageroo now provides full vision support."
        )
        self.assertFalse(claim_is_explicitly_denied(repeated, "full vision support"))
        self.assertEqual(len(find_overclaim_offenders(repeated, ["full vision support"])), 1)
        self.assertFalse(
            claim_is_explicitly_denied(
                "Manageroo needs no setup for full vision support.",
                "full vision support",
            )
        )
        self.assertTrue(
            claim_is_explicitly_denied(
                "Manageroo provides no full vision support.",
                "full vision support",
            )
        )

    def test_authorization_language_requires_demonstration_evidence(self):
        for outcome in (
            "Unauthorized users cannot delete projects.",
            "Authorization policy prevents privilege escalation.",
            "Access control blocks the wrong role.",
        ):
            with self.subTest(outcome=outcome):
                self.assertTrue(_needs_demonstration(outcome))
                rows = build_acceptance_evidence(
                    product={"acceptance_outcomes": [outcome]},
                    gate_results=[{"gate": {"id": "security-test"}, "result": {"exit_code": 0}}],
                    demonstration={
                        "gates": [],
                        "product_evidence": [{"outcome": outcome, "gate_ids": ["security-test"]}],
                    },
                    review={"status": "approved", "findings": []},
                )
                self.assertEqual(rows[0]["status"], "unknown")

    def test_zero_evidence_limits_return_no_items(self):
        self.assertEqual(normalize_external_payload(provider="x", payload="plain evidence", limit=0), [])
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir()
            memory.write_text("matching memory", encoding="utf-8")
            self.assertEqual(ProjectMemoryEvidenceProvider(repo).retrieve("matching", limit=0), [])

    def test_skill_scan_detects_supporting_file_only_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "demo"
            target_root = root / "target"
            target = target_root / "demo"
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            skill = "---\nname: demo\n---\n# Demo\n"
            (source / "SKILL.md").write_text(skill, encoding="utf-8")
            (target / "SKILL.md").write_text(skill, encoding="utf-8")
            (source / "helper.txt").write_text("new", encoding="utf-8")
            (target / "helper.txt").write_text("old", encoding="utf-8")
            report = scan_skill_folder(root / "source", skills_dir=target_root)
            self.assertEqual(report["candidates"][0]["status"], "conflict")
            imported = import_skill_folder(root / "source", skills_dir=target_root, apply=True)
            self.assertEqual((target / "helper.txt").read_text(encoding="utf-8"), "new")
            backup = Path(imported["imported"][0]["backup"])
            self.assertEqual((backup / "helper.txt").read_text(encoding="utf-8"), "old")

    def test_forced_chiptune_stop_reaps_killed_child(self):
        playback = ThemePlayback(enabled=False)
        process = _KilledProcess()
        playback._process = process
        playback.stop()
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertGreaterEqual(process.wait_calls, 2)

    def test_gbrain_unembedded_chunks_are_not_ready(self):
        summary = summarize_sync_status(
            json.dumps(
                {
                    "sync": {
                        "sources": [
                            {
                                "source_id": "docs",
                                "chunks_total": 100,
                                "chunks_unembedded": 100,
                                "embedding_coverage_pct": 0,
                            }
                        ],
                        "unacknowledged_failures": 0,
                    }
                }
            )
        )
        self.assertFalse(summary["ok"])
        self.assertFalse(summary["healthy"])
        self.assertFalse(summary["embeddings_ready"])


if __name__ == "__main__":
    unittest.main()
