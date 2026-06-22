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
            memory = repo / ".umsmfburasbofe" / "PROJECT-MEMORY.md"
            self.assertTrue(memory.exists())
            memory_text = memory.read_text(encoding="utf-8")
            self.assertIn("## What This Project Is", memory_text)
            self.assertIn("## What Has Shipped", memory_text)
            self.assertIn("## What Must Not Break", memory_text)
            agents_text = (repo / "AGENTS.md").read_text(encoding="utf-8")
            context_text = (repo / "CONTEXT.md").read_text(encoding="utf-8")
            self.assertIn(".umsmfburasbofe/PROJECT-MEMORY.md", agents_text)
            self.assertIn("brain-ops", agents_text)
            self.assertIn("exact-text-replacement", agents_text)
            self.assertIn(".umsmfburasbofe/PROJECT-MEMORY.md", context_text)
            self.assertIn("document/prose lane", context_text)
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

    def test_create_project_repo_static_site_starter_has_files_and_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "launch-site"
            result = create_project_repo(
                repo,
                title="Launch Site",
                description="Make the product easy to understand.",
                starter="static-site",
            )
            self.assertEqual(result["starter"], "static-site")
            self.assertIn("index.html", result["created_files"])
            self.assertTrue((repo / "index.html").exists())
            self.assertTrue((repo / "styles.css").exists())
            self.assertTrue((repo / "tests" / "test_static_site.py").exists())
            initialized = initialize_project(repo, agent="mock")
            gate_ids = {gate["id"] for gate in initialized["detected_gates"]}
            self.assertIn("unittest", gate_ids)

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
