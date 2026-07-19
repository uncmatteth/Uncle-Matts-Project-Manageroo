import io
import sys
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.entrypoint import main


ROOT = Path(__file__).resolve().parents[1]


class CliSmokeTests(unittest.TestCase):
    def test_console_script_points_to_public_entrypoint(self):
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        self.assertEqual(project["project"]["scripts"]["manageroo"], "manageroo.entrypoint:main")

    def test_public_help_entrypoint_constructs_and_exits_cleanly(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "--help"]), redirect_stdout(output):
            code = main()
        self.assertEqual(code, 0)
        rendered = output.getvalue()
        self.assertIn("manageroo", rendered.lower())
        self.assertIn("prove", rendered)
        self.assertIn("stack-update", rendered)


if __name__ == "__main__":
    unittest.main()
