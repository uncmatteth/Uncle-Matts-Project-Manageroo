from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.adapters.mock import MockAdapter
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.util import read_json


class PolicyBootstrapContractTests(unittest.TestCase):
    def test_package_import_installs_external_repair_lane(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            for argv in (
                ["git", "init", "-q", "-b", "main"],
                ["git", "config", "user.name", "MANAGEROO Tests"],
                ["git", "config", "user.email", "tests@local.invalid"],
            ):
                subprocess.run(argv, cwd=repo, check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("needs repair\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "fixture"],
                cwd=repo,
                check=True,
            )
            initialize_project(repo, agent="mock")
            orchestrator = Orchestrator(repo, adapter=MockAdapter())
            orchestrator.workspace = orchestrator.mirror.create()

            def repair_lane(**kwargs):
                (kwargs["cwd"] / "tracked.txt").write_text("repaired\n", encoding="utf-8")
                return {"name": "clawpatch", "enabled": True, "ok": True, "exit_code": 0}

            with (
                patch.object(
                    orchestrator,
                    "_external_review_repair_commands",
                    return_value=[("clawpatch", ["fake-clawpatch"])],
                ),
                patch.object(
                    orchestrator,
                    "_run_optional_external_command",
                    side_effect=repair_lane,
                ),
            ):
                result = orchestrator._run_external_review_repair_lanes(
                    brief="Repair the tracked finding.",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(
                (orchestrator.workspace / "tracked.txt").read_text(encoding="utf-8"),
                "repaired\n",
            )
            self.assertEqual(result["summary"]["passed"], ["clawpatch"])
            self.assertEqual(result["summary"]["changed_paths"], ["tracked.txt"])
            artifact = read_json(
                orchestrator.artifacts.root / "review" / "external-review-repair.json"
            )
            self.assertTrue(artifact["summary"]["command_owned_repair_lanes"])
            self.assertFalse(artifact["summary"]["ai_freehand_repair_allowed"])


if __name__ == "__main__":
    unittest.main()
