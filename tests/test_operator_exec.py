from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.errors import ConfigurationError
from manageroo.operator_exec import operator_exec


class OperatorExecTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        return repo

    def test_opaque_command_uses_native_workspace_sandbox_without_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            with patch("manageroo.operator_exec.shutil.which", return_value="/usr/bin/codex"), patch(
                "manageroo.operator_exec.subprocess.run",
                return_value=subprocess.CompletedProcess([], 7),
            ) as run:
                code = operator_exec(repo, ["python3", "scripts/check.py"])

            self.assertEqual(code, 7)
            run.assert_called_once_with(
                [
                    "/usr/bin/codex",
                    "sandbox",
                    "--permission-profile",
                    ":workspace",
                    "-C",
                    str(repo),
                    "--",
                    "python3",
                    "scripts/check.py",
                ],
                cwd=repo,
                check=False,
            )

    def test_missing_codex_and_nested_wrapper_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            with patch("manageroo.operator_exec.shutil.which", return_value=None):
                with self.assertRaisesRegex(ConfigurationError, "requires the local Codex CLI"):
                    operator_exec(repo, ["python3", "check.py"])
            with self.assertRaisesRegex(ConfigurationError, "Nested"):
                operator_exec(repo, ["manageroo", "operator-exec", "--repo", str(repo), "--", "ls"])


if __name__ == "__main__":
    unittest.main()
