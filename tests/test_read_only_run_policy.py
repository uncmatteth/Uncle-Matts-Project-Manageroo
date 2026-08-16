from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.mock import MockAdapter
from manageroo.agent_continuity import (
    capture_current_request,
    process_codex_continuity_hook,
)
from manageroo.errors import SafetyError
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.release_proof_policy import source_tree_digest
from manageroo.runner import CommandRunner


class ReadOnlyRunPolicyTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Read Only Test"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "readonly@example.invalid"],
            cwd=repo,
            check=True,
        )
        (repo / ".gitignore").write_text(
            ".manageroo/runs/\n.manageroo/cache/\n",
            encoding="utf-8",
        )
        (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "baseline"], cwd=repo, check=True
        )
        initialize_project(repo, agent="mock")
        config = repo / ".manageroo" / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8")
            + "\n[[verification.gates]]\n"
            + 'id = "audit-check"\n'
            + 'kind = "test"\n'
            + "required = true\n"
            + "timeout_seconds = 60\n"
            + "argv = ["
            + json.dumps(sys.executable)
            + ', "-c", "from pathlib import Path; '
            + "raise SystemExit(0 if Path('README.md').read_text() == '# Fixture\\n' else 1)"
            + '"]\n',
            encoding="utf-8",
        )
        return repo

    def _request(self, repo: Path, state_root: Path) -> dict:
        return capture_current_request(
            session_id="read-only-session",
            turn_id="turn-1",
            prompt=(
                "Review this repository and tell me what is wrong. "
                "Do not change anything."
            ),
            cwd=str(repo),
            state_root=state_root,
        )

    def test_public_read_only_request_completes_with_zero_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "continuity"
            request = self._request(repo, state_root)
            runner = CommandRunner()
            before = source_tree_digest(repo, runner)

            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=Path(request["managed_request_path"]),
                mode="build",
                apply_on_success=False,
            )

            after = source_tree_digest(repo, runner)
            run_root = repo / ".manageroo" / "runs" / result["run_id"]
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["mode"], "audit")
            self.assertFalse(result["applied_to_source"])
            self.assertEqual(result["files_changed"], [])
            self.assertEqual(before, after)
            self.assertEqual((run_root / "delivery" / "final.patch").stat().st_size, 0)
            self.assertTrue((run_root / "delivery" / "completion-receipt.json").is_file())
            self.assertTrue((run_root / "artifacts" / "review" / "review.json").is_file())
            self.assertFalse((repo / "manageroo_fixture.txt").exists())

            stopped = process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "read-only-session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "stop_hook_active": False,
                },
                state_root=state_root,
            )
            self.assertEqual(stopped, {})

    def test_read_only_request_rejects_apply_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            request = self._request(repo, root / "continuity")
            with self.assertRaisesRegex(SafetyError, "cannot receive apply authority"):
                Orchestrator(repo, adapter=MockAdapter()).run(
                    brief_path=Path(request["managed_request_path"]),
                    mode="build",
                    apply_on_success=True,
                )
            self.assertFalse((repo / "manageroo_fixture.txt").exists())


if __name__ == "__main__":
    unittest.main()
