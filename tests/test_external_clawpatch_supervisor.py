from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tomllib
import unittest

from manageroo.clawpatch_external import main


class ExternalClawpatchSupervisorTests(unittest.TestCase):
    def test_package_installs_external_supervisor_command(self):
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(
            project["scripts"]["clawpatch-supervise"],
            "manageroo.clawpatch_external:main",
        )

    def test_terminal_command_shows_finding_counter_commands_and_same_finding_retry(self):
        calls = []

        def fake_sweep(repo: Path, **kwargs):
            calls.append((repo, kwargs))
            progress = kwargs["progress"]
            progress(
                {
                    "phase": "map",
                    "current": "?",
                    "total": "?",
                    "command": "clawpatch map --json",
                    "attempt": 1,
                    "max_attempts": 3,
                }
            )
            progress(
                {
                    "phase": "finding",
                    "current": 1,
                    "total": 88,
                    "finding_id": "fnd_one",
                    "command": "clawpatch show --finding fnd_one",
                    "inspection": {
                        "finding": {
                            "id": "fnd_one",
                            "title": "Broken rollback",
                            "severity": "high",
                            "category": "data-loss",
                            "recommendation": "Track publication state.",
                            "reproduction": "Fail the first rename.",
                            "minimumFixScope": "Fix rollback and add a test.",
                            "evidence": [{"path": "release.py", "startLine": 10, "endLine": 20}],
                        },
                        "validation": ["pytest"],
                    },
                }
            )
            progress(
                {
                    "phase": "fix",
                    "current": 1,
                    "total": 88,
                    "finding_id": "fnd_one",
                    "retry": 0,
                    "attempt": 1,
                    "command": "clawpatch fix --finding fnd_one",
                }
            )
            progress(
                {
                    "phase": "retry",
                    "current": 1,
                    "total": 88,
                    "finding_id": "fnd_one",
                    "retry": 1,
                    "outcome": "fix-validation-failed",
                    "error": "validation failed",
                }
            )
            progress(
                {
                    "phase": "fix",
                    "current": 1,
                    "total": 88,
                    "finding_id": "fnd_one",
                    "retry": 1,
                    "attempt": 2,
                    "command": "clawpatch fix --finding fnd_one",
                }
            )
            progress(
                {
                    "phase": "fixed",
                    "current": 1,
                    "total": 88,
                    "finding_id": "fnd_one",
                    "commit": "abc123",
                }
            )
            return {"ok": True, "finding_count": 1, "open_findings": 0, "git_head": "abc123"}

        output = StringIO()
        with redirect_stdout(output):
            code = main(["--repo", "."], run_sweep=fake_sweep, heartbeat_seconds=0)

        rendered = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[?/?] MAP (attempt 1/3)", rendered)
        self.assertIn("$ clawpatch map --json", rendered)
        self.assertIn("[1/88] SHOW", rendered)
        self.assertIn("clawpatch show --finding fnd_one", rendered)
        self.assertIn("Broken rollback", rendered)
        self.assertIn("release.py:10-20", rendered)
        self.assertIn("[1/88] FIX", rendered)
        self.assertIn("clawpatch fix --finding fnd_one", rendered)
        self.assertIn("[1/88] RETRY 1", rendered)
        self.assertIn("same finding", rendered)
        self.assertIn("[1/88] FIX (attempt 2)", rendered)
        self.assertNotIn("RECOVERY CYCLE", rendered)
        self.assertIn("[1/88] FIXED", rendered)
        self.assertEqual(calls[0][1]["branch"], "current")
        self.assertEqual(calls[0][1]["push_mode"], "each")


if __name__ == "__main__":
    unittest.main()
