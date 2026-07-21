import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.acceptance import _needs_demonstration, build_acceptance_evidence
from manageroo.chiptune import ThemePlayback
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
                result = CommandRunner().run(["tool"], cwd=Path(temp), timeout_seconds=1)
        self.assertTrue(result.timed_out)
        self.assertIn("partial stdout", result.stdout)
        self.assertIn("partial stderr", result.stderr)

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
        playback.process = process
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
