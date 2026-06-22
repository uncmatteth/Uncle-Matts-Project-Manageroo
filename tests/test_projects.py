import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from umsmfburasbofe.cli import main
from umsmfburasbofe.projects import default_project_roots


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
            (initialized / ".umsmfburasbofe").mkdir()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["projects", "--root", str(root), "--json"])

            payload = json.loads(stdout.getvalue())
            by_name = {item["name"]: item for item in payload["projects"]}
            self.assertEqual(code, 0)
            self.assertEqual(payload["ok"], True)
            self.assertEqual(by_name["plain-repo"]["status"], "git repo")
            self.assertEqual(by_name["plain-repo"]["next_command"], f"umsmfburasbofe solo {repo}")
            self.assertEqual(by_name["already-ready"]["status"], "initialized")
            self.assertEqual(
                by_name["already-ready"]["next_command"],
                f"umsmfburasbofe next {initialized}",
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
            self.assertIn(f"Next: umsmfburasbofe solo {repo}", output)
            self.assertIn("New project:", output)
            self.assertIn("umsmfburasbofe solo /path/to/new-project --create", output)

    def test_default_roots_do_not_scan_the_whole_home_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            github = home / "Documents" / "GitHub"
            github.mkdir(parents=True)

            roots = default_project_roots(home=home, cwd=home)

            self.assertNotIn(home.resolve(), roots)
            self.assertIn(github.resolve(), roots)


if __name__ == "__main__":
    unittest.main()
