from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from manageroo.run_retention import enforce_run_retention


class RunRetentionTests(unittest.TestCase):
    def _complete_run(self, repo: Path, run_id: str, *, packet_bytes: int = 0) -> Path:
        run_root = repo / ".manageroo" / "runs" / run_id
        (run_root / "delivery").mkdir(parents=True)
        (run_root / "controller").mkdir()
        (run_root / "state.json").write_text(
            json.dumps({"phase": "COMPLETE"}), encoding="utf-8"
        )
        (run_root / "delivery" / "final-result.json").write_text(
            json.dumps({"status": "COMPLETE", "run_id": run_id}), encoding="utf-8"
        )
        (run_root / "delivery" / "final.patch").write_text("", encoding="utf-8")
        if packet_bytes:
            packets = run_root / "packets"
            packets.mkdir()
            (packets / "payload.txt").write_bytes(b"x" * packet_bytes)
        return run_root

    def _canceled_run(self, repo: Path, run_id: str) -> Path:
        run_root = repo / ".manageroo" / "runs" / run_id
        (run_root / "controller").mkdir(parents=True)
        (run_root / "state.json").write_text(
            json.dumps({"phase": "IMPLEMENTING"}), encoding="utf-8"
        )
        (run_root / "controller" / "workspace-lifecycle.json").write_text(
            json.dumps({"status": "CANCELED", "run_id": run_id}), encoding="utf-8"
        )
        return run_root

    def test_complete_run_evidence_is_compacted_to_configured_byte_quota(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            run_root = self._complete_run(repo, "run-current", packet_bytes=200_000)

            report = enforce_run_retention(
                repo,
                current_run_id="run-current",
                config={
                    "max_run_count": 40,
                    "max_run_age_days": 30,
                    "max_run_evidence_bytes": 20_000,
                },
            )

            self.assertFalse((run_root / "packets").exists())
            self.assertTrue((run_root / "delivery" / "final-result.json").is_file())
            self.assertLessEqual(report["current_run"]["bytes_after"], 20_000)
            self.assertTrue(report["current_run"]["quota_satisfied"])

    def test_oldest_terminal_runs_are_removed_at_configured_count(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            oldest = self._complete_run(repo, "run-oldest")
            middle = self._complete_run(repo, "run-middle")
            current = self._complete_run(repo, "run-current")
            os.utime(oldest, (1, 1))
            os.utime(middle, (2, 2))
            os.utime(current, (3, 3))

            report = enforce_run_retention(
                repo,
                current_run_id="run-current",
                config={
                    "max_run_count": 2,
                    "max_run_age_days": 30_000,
                    "max_run_evidence_bytes": 20_000,
                },
            )

            self.assertFalse(oldest.exists())
            self.assertTrue(middle.is_dir())
            self.assertTrue(current.is_dir())
            self.assertEqual(report["removed_runs"], ["run-oldest"])

    def test_canceled_run_is_terminal_for_retention(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            canceled = self._canceled_run(repo, "run-canceled")
            current = self._complete_run(repo, "run-current")
            os.utime(canceled, (1, 1))
            os.utime(current, (2, 2))

            report = enforce_run_retention(
                repo,
                current_run_id="run-current",
                config={
                    "max_run_count": 1,
                    "max_run_age_days": 30_000,
                    "max_run_evidence_bytes": 20_000,
                },
            )

            self.assertFalse(canceled.exists())
            self.assertEqual(report["removed_runs"], ["run-canceled"])


if __name__ == "__main__":
    unittest.main()
