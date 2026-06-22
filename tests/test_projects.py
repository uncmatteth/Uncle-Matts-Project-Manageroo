import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.cli import main
from manageroo.projects import default_project_roots, selected_project_paths


class ProjectDiscoveryTests(unittest.TestCase):
    def _git_repo(self, root: Path, name: str) -> Path:
        repo = root / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        return repo

    def test_projects_json_finds_git_repos_and_next_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._git_repo(root, "plain-repo")
            initialized = self._git_repo(root, "already-ready")
            (initialized / ".manageroo").mkdir()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["projects", "--root", str(root), "--json"])

            payload = json.loads(stdout.getvalue())
            by_name = {item["name"]: item for item in payload["projects"]}
            self.assertEqual(code, 0)
            self.assertEqual(payload["ok"], True)
            self.assertEqual(by_name["plain-repo"]["status"], "git repo")
            self.assertEqual(by_name["plain-repo"]["next_command"], f"manageroo solo {repo}")
            self.assertEqual(by_name["already-ready"]["status"], "initialized")
            self.assertEqual(
                by_name["already-ready"]["next_command"],
                f"manageroo next {initialized}",
            )

    def test_projects_text_explains_the_picker_and_new_project_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._git_repo(root, "product")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["projects", "--root", str(root)])

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("PROJECT PICKER", output)
            self.assertIn(str(repo), output)
            self.assertIn(f"Next: manageroo solo {repo}", output)
            self.assertIn("New project:", output)
            self.assertIn("manageroo solo /path/to/new-project --create", output)

    def test_default_roots_do_not_scan_the_whole_home_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            github = home / "Documents" / "GitHub"
            github.mkdir(parents=True)

            roots = default_project_roots(home=home, cwd=home)

            self.assertNotIn(home.resolve(), roots)
            self.assertIn(github.resolve(), roots)

    def test_selected_project_paths_accepts_checkbox_style_numbers_ranges_and_all(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            alpha = self._git_repo(root, "alpha")
            beta = self._git_repo(root, "beta")
            gamma = self._git_repo(root, "gamma")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["projects", "--root", str(root), "--json"])
            self.assertEqual(code, 0)
            report = json.loads(stdout.getvalue())

            self.assertEqual(selected_project_paths(report, "1, 3"), [alpha.resolve(), gamma.resolve()])
            self.assertEqual(selected_project_paths(report, "1-2"), [alpha.resolve(), beta.resolve()])
            self.assertEqual(selected_project_paths(report, "all"), [alpha.resolve(), beta.resolve(), gamma.resolve()])

    def test_projects_add_initializes_selected_found_projects_and_manual_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "scanned"
            root.mkdir()
            alpha = self._git_repo(root, "alpha")
            beta = self._git_repo(root, "beta")
            manual_root = Path(temp) / "manual"
            manual_root.mkdir()
            extra = self._git_repo(manual_root, "extra")

            stdout = io.StringIO()
            answers = iter(["1", str(extra), ""])
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", side_effect=lambda _prompt="": next(answers)):
                    with redirect_stdout(stdout):
                        code = main(["projects", "--root", str(root), "--add", "--agent", "mock"])

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("PROJECT SETUP CHECKLIST", output)
            self.assertIn("[ ] 1.", output)
            self.assertIn("Which projects do you want to add", output)
            self.assertIn("Add another project folder path", output)
            self.assertIn("[x] alpha", output)
            self.assertIn("[x] extra", output)
            self.assertTrue((alpha / ".manageroo" / "config.toml").exists())
            self.assertTrue((extra / ".manageroo" / "config.toml").exists())
            self.assertFalse((beta / ".manageroo").exists())

    def test_projects_add_can_create_missing_manual_project_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            new_project = root / "new-product"

            stdout = io.StringIO()
            answers = iter(["", str(new_project), ""])
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", side_effect=lambda _prompt="": next(answers)):
                    with redirect_stdout(stdout):
                        code = main(["projects", "--root", str(root), "--add", "--agent", "mock"])

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("[x] new-product", output)
            self.assertTrue((new_project / ".git").is_dir())
            self.assertTrue((new_project / ".manageroo" / "config.toml").exists())


if __name__ == "__main__":
    unittest.main()
