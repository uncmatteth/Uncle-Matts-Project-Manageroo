import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.runner import CommandRunner
from manageroo.workspace import WorkspaceMirror


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "tag.gpgSign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


class WorkspaceHostileGitConfigTests(unittest.TestCase):
    def test_controller_commits_ignore_global_signing_and_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            _git(source, "init", "-q", "-b", "main")
            _git(source, "config", "user.name", "Manageroo Tests")
            _git(source, "config", "user.email", "tests@local.invalid")
            (source / "tracked.txt").write_text("baseline\n", encoding="utf-8")
            _git(source, "add", "-A")
            _git(source, "commit", "-q", "-m", "source baseline")

            hooks = root / "hostile-hooks"
            hooks.mkdir()
            pre_commit = hooks / "pre-commit"
            pre_commit.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            pre_commit.chmod(0o755)
            global_config = root / "hostile.gitconfig"
            global_config.write_text(
                "[commit]\n"
                "\tgpgSign = true\n"
                "[tag]\n"
                "\tgpgSign = true\n"
                "[core]\n"
                f"\thooksPath = {hooks.as_posix()}\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "GIT_CONFIG_GLOBAL": str(global_config),
                    "GIT_CONFIG_NOSYSTEM": "1",
                },
            ):
                mirror = WorkspaceMirror(source, root / "run", CommandRunner())
                workspace = mirror.create()
                (workspace / "tracked.txt").write_text("checkpoint\n", encoding="utf-8")
                checkpoint = mirror.checkpoint("controller checkpoint")

            self.assertTrue(checkpoint)
            self.assertEqual(mirror.head(), checkpoint)
            self.assertEqual((workspace / "tracked.txt").read_text(encoding="utf-8"), "checkpoint\n")


if __name__ == "__main__":
    unittest.main()
