import contextlib
import io
import sys
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo import __version__
from manageroo.cli import parser
from manageroo.entrypoint import main as entrypoint_main


ROOT = Path(__file__).resolve().parents[1]


class CliEntrypointSmokeTests(unittest.TestCase):
    def test_console_script_points_to_manageroo_entrypoint_main(self):
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        self.assertEqual(project["project"]["scripts"]["manageroo"], "manageroo.entrypoint:main")

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

    def test_document_analyze_command_accepts_manifest_and_workspace(self):
        args = parser().parse_args(
            ["document-analyze", "/tmp/manifest.json", "/tmp/workspace"]
        )
        self.assertEqual(args.command, "document-analyze")
        self.assertEqual(args.manifest, Path("/tmp/manifest.json"))
        self.assertEqual(args.workspace, Path("/tmp/workspace"))

    def test_configured_entrypoint_forwards_version_behavior(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "--version"]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                entrypoint_main()
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), __version__)

    def test_configured_entrypoint_root_help_executes_successfully(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "--help"]), contextlib.redirect_stdout(output):
            code = entrypoint_main()
        self.assertEqual(code, 0)
        self.assertIn("usage: manageroo", output.getvalue().lower())

    def test_bare_manageroo_discovers_projects_then_accepts_a_plain_english_request(self):
        project = Path("/projects/Uncle-Matts-Randomifier-Hood")
        discovery = {
            "ok": True,
            "projects": [
                {
                    "name": "Swipeys-NFT-Contract",
                    "path": "/projects/Swipeys-NFT-Contract",
                    "status": "initialized",
                },
                {
                    "name": project.name,
                    "path": str(project),
                    "status": "git repo",
                }
            ],
            "count": 1,
        }
        output = io.StringIO()
        request = "fix the checkout bug in randomifier hood"
        with (
            patch.object(sys, "argv", ["manageroo"]),
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("manageroo.entrypoint.discover_projects", return_value=discovery) as discover,
            patch("manageroo.entrypoint.cli_main", return_value=0) as routed,
            patch("builtins.input", return_value=request),
            contextlib.redirect_stdout(output),
        ):
            code = entrypoint_main()

        self.assertEqual(code, 0)
        self.assertIn("Hi! I'm Manageroo! Let's do!", output.getvalue())
        discover.assert_called_once_with(limit=0, agent="auto")
        routed.assert_called_once_with(
            [
                "solo",
                str(project),
                "--agent",
                "auto",
                "--want",
                request,
                "--run",
            ]
        )

    def test_bare_manageroo_prepares_request_without_implicit_run_or_apply(self):
        args = parser().parse_args(["solo", "/tmp/project", "--want", "fix it"])
        self.assertFalse(args.run)
        self.assertFalse(args.apply)


if __name__ == "__main__":
    unittest.main()
