import subprocess
import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.project import create_project_repo, initialize_project


class ProjectInitializationTests(unittest.TestCase):
    def test_initialization_is_editor_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            self.assertTrue((repo / ".umsmfburasbofe" / "config.toml").exists())
            self.assertTrue(
                (
                    repo
                    / ".agents"
                    / "skills"
                    / "uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition"
                    / "SKILL.md"
                ).exists()
            )
            self.assertFalse((repo / ".vscode").exists())
            self.assertFalse((repo / "CLAUDE.md").exists())

    def test_create_project_repo_initializes_missing_folder_with_first_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "new-product"
            result = create_project_repo(
                repo,
                title="New Product",
                description="Make the first release less painful.",
            )
            self.assertEqual(Path(result["repo"]), repo)
            self.assertTrue((repo / ".git").is_dir())
            self.assertIn("New Product", (repo / "README.md").read_text(encoding="utf-8"))
            self.assertIn(".umsmfburasbofe/runs/", (repo / ".gitignore").read_text(encoding="utf-8"))
            head = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertTrue(head.stdout.strip())

    def test_create_project_repo_refuses_non_empty_non_git_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "existing"
            repo.mkdir()
            (repo / "notes.txt").write_text("keep this\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                create_project_repo(repo, title="Existing")

    def test_create_project_repo_refuses_nested_repo_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "outer"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            nested = repo / "nested"
            with self.assertRaises(ValueError):
                create_project_repo(nested, title="Nested")


if __name__ == "__main__":
    unittest.main()
