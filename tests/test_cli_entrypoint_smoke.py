import contextlib
import io
import tomllib
import unittest
from pathlib import Path

from manageroo import __version__
from manageroo.cli import parser


ROOT = Path(__file__).resolve().parents[1]


class CliEntrypointSmokeTests(unittest.TestCase):
    def test_console_script_points_to_manageroo_cli_main(self):
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        self.assertEqual(project["project"]["scripts"]["manageroo"], "manageroo.cli:main")

    def test_parser_builds_and_help_exits_successfully(self):
        built = parser()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            built.parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("usage: manageroo", output.getvalue().lower())

    def test_version_exits_successfully_and_reports_package_version(self):
        built = parser()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            built.parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), __version__)


if __name__ == "__main__":
    unittest.main()
