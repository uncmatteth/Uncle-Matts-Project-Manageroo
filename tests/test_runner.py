import json
import sys
import tempfile
import unittest
from pathlib import Path

from manageroo.errors import SafetyError
from manageroo.runner import CommandRunner


class CommandRunnerTests(unittest.TestCase):
    def test_log_name_rejects_path_escape_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logs = root / "logs"
            marker = root / "command-ran"
            runner = CommandRunner(logs)
            unsafe_names = (
                "../victim",
                str((root / "absolute-victim").resolve()),
                "nested/name",
                "nested\\name",
                "",
                ".",
                "..",
            )

            for log_name in unsafe_names:
                with self.subTest(log_name=log_name):
                    with self.assertRaises(SafetyError):
                        runner.run(
                            [
                                sys.executable,
                                "-c",
                                f"from pathlib import Path; Path({str(marker)!r}).touch()",
                            ],
                            cwd=root,
                            log_name=log_name,
                            kill_process_group=False,
                        )

            self.assertFalse(marker.exists())
            self.assertFalse((root / "victim.json").exists())
            self.assertFalse((root / "absolute-victim.json").exists())

    def test_simple_log_name_writes_beneath_log_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logs = root / "logs"
            result = CommandRunner(logs).run(
                [sys.executable, "-c", "print('ok')"],
                cwd=root,
                log_name="safe-command",
                kill_process_group=False,
            )

            log_path = logs / "safe-command.json"
            self.assertTrue(result.passed)
            self.assertTrue(log_path.is_file())
            self.assertEqual(json.loads(log_path.read_text(encoding="utf-8"))["stdout"], "ok\n")


if __name__ == "__main__":
    unittest.main()
