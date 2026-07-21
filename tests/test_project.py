import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.project import create_project_repo, initialize_project
from manageroo.project_memory import ensure_project_memory


class ProjectInitializationTests(unittest.TestCase):
    def test_initialization_is_editor_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            self.assertTrue((repo / ".manageroo" / "config.toml").exists())
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            self.assertTrue(memory.exists())
            memory_text = memory.read_text(encoding="utf-8")
            self.assertIn("## What This Project Is", memory_text)
            self.assertIn("## What Has Shipped", memory_text)
            self.assertIn("## What Must Not Break", memory_text)
            agents_text = (repo / "AGENTS.md").read_text(encoding="utf-8")
            context_text = (repo / "CONTEXT.md").read_text(encoding="utf-8")
            self.assertIn(".manageroo/PROJECT-MEMORY.md", agents_text)
            self.assertIn("host-owned", agents_text)
            self.assertIn("portable core", agents_text)
            self.assertIn(".manageroo/PROJECT-MEMORY.md", context_text)
            self.assertIn("document/prose lane", context_text)
            self.assertTrue(
                (
                    repo
                    / ".agents"
                    / "skills"
                    / "uncle-matts-project-manageroo"
                    / "SKILL.md"
                ).exists()
            )
            self.assertFalse((repo / ".vscode").exists())
            self.assertFalse((repo / "CLAUDE.md").exists())

    def test_real_memory_values_replace_generated_placeholder_bullets(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            ensure_project_memory(repo)
            ensure_project_memory(
                repo,
                project_summary="A real project summary.",
                shipped=["Version 1 released."],
                must_not=["Never delete customer data."],
                proof=["Run the end-to-end smoke test."],
            )
            text = (repo / ".manageroo" / "PROJECT-MEMORY.md").read_text(encoding="utf-8")
            for value in (
                "A real project summary.",
                "Version 1 released.",
                "Never delete customer data.",
                "Run the end-to-end smoke test.",
            ):
                self.assertIn(value, text)
            for placeholder in (
                "Describe the durable identity and purpose of this project.",
                "Nothing shipped through MANAGEROO yet.",
                "Add the invariants that future work must preserve.",
                "Record the strongest reliable proof commands and user journeys here.",
            ):
                self.assertNotIn(placeholder, text)

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
            self.assertIn(".manageroo/runs/", (repo / ".gitignore").read_text(encoding="utf-8"))
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

    def test_existing_empty_git_repo_can_receive_requested_starter_non_destructively(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "existing-empty"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            result = create_project_repo(
                repo,
                title="Existing Empty",
                description="Scaffold this empty repository.",
                starter="static-site",
            )
            self.assertEqual(result["status"], "scaffolded-existing-git")
            self.assertIn("index.html", result["created_files"])
            self.assertTrue((repo / "index.html").is_file())
            self.assertTrue((repo / "styles.css").is_file())

    def test_initialization_preflights_non_utf8_instruction_file_before_mutating_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            agents = repo / "AGENTS.md"
            original = b"prefix\xffsuffix"
            agents.write_bytes(original)
            before = {path.relative_to(repo).as_posix(): path.read_bytes() for path in repo.iterdir() if path.is_file()}
            with self.assertRaises(ValueError):
                initialize_project(repo, agent="mock")
            after = {path.relative_to(repo).as_posix(): path.read_bytes() for path in repo.iterdir() if path.is_file()}
            self.assertEqual(after, before)
            self.assertEqual(agents.read_bytes(), original)
            self.assertFalse((repo / ".manageroo").exists())
            self.assertFalse((repo / ".agents").exists())
            self.assertFalse((repo / "CONTEXT.md").exists())

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
