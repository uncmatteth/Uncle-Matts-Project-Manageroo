import multiprocessing
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manageroo.project as project_module
from manageroo.errors import SafetyError
from manageroo.project import create_project_repo, initialize_project
from manageroo.project_memory import ensure_project_memory


def _update_project_memory_after_synchronized_read(
    repo: str,
    field: str,
    value: str,
    read_reached,
    release_read,
    finished,
    results,
) -> None:
    import manageroo.project_memory as project_memory_module

    original_read = project_memory_module._read_utf8
    first_read = True

    def synchronized_read(*args, **kwargs):
        nonlocal first_read
        content = original_read(*args, **kwargs)
        if first_read:
            first_read = False
            read_reached.set()
            if release_read is not None and not release_read.wait(timeout=5):
                raise RuntimeError("timed out waiting to release project-memory read")
        return content

    project_memory_module._read_utf8 = synchronized_read
    try:
        ensure_project_memory(Path(repo), **{field: [value]})
    except Exception as exc:
        results.put(f"{type(exc).__name__}: {exc}")
    else:
        results.put("ok")
    finally:
        finished.set()


class ProjectInitializationTests(unittest.TestCase):
    def test_operator_facing_manageroo_guidance_acts_without_permission_theater(self):
        root = Path(__file__).resolve().parents[1]
        skill = (
            root
            / "src"
            / "manageroo"
            / "assets"
            / "skills"
            / "uncle-matts-project-manageroo"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        ide_guides = "\n".join(
            (root / relative).read_text(encoding="utf-8")
            for relative in (
                "GIVE-THIS-TO-YOUR-IDE-AGENT.md",
                "docs/IDE_AGENT_INSTALL_INSTRUCTIONS.md",
            )
        )

        self.assertNotIn("First-install request policy", skill)
        self.assertNotIn("the user should preferably run the installer", skill)
        self.assertNotIn("gather their selections instead of guessing", skill)
        self.assertIn("Act immediately", skill)
        self.assertIn("operator-facing agent", skill)
        self.assertIn("commit, push, and deploy", skill)

        self.assertNotIn("If any input is missing, stop", ide_guides)
        self.assertNotIn("Do not run a real build until the operator completes", ide_guides)
        self.assertNotIn("Stop if `ready.ok` is false", ide_guides)
        self.assertIn("infer every value that current files and the operator request make clear", ide_guides)
        self.assertIn("execute the safe next action", ide_guides)

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
            self.assertIn("plain everyday English", agents_text)
            self.assertIn("what happened, what it means, and what to do next", agents_text)
            self.assertIn("unless the operator explicitly asks", agents_text)
            self.assertIn("Manageroo-controlled workers", agents_text)
            self.assertIn("operator-facing agent", agents_text)
            self.assertIn("commit, push, and deploy", agents_text)
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
                "Describe what this project is for.",
                "Nothing shipped through MANAGEROO yet.",
                "Add product promises, workflows, files, or behaviors that must stay intact.",
                "Add the commands or manual checks that prove the current state.",
            ):
                self.assertNotIn(placeholder, text)

    def test_concurrent_project_memory_updates_preserve_all_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            ensure_project_memory(repo)
            context = multiprocessing.get_context("spawn")
            first_read = context.Event()
            release_first_read = context.Event()
            first_finished = context.Event()
            second_read = context.Event()
            second_finished = context.Event()
            results = context.Queue()
            first = context.Process(
                target=_update_project_memory_after_synchronized_read,
                args=(
                    str(repo),
                    "shipped",
                    "Concurrent shipped item.",
                    first_read,
                    release_first_read,
                    first_finished,
                    results,
                ),
            )
            second = context.Process(
                target=_update_project_memory_after_synchronized_read,
                args=(
                    str(repo),
                    "notes",
                    "Concurrent operator note.",
                    second_read,
                    None,
                    second_finished,
                    results,
                ),
            )

            try:
                first.start()
                self.assertTrue(first_read.wait(timeout=5))
                second.start()
                if second_read.wait(timeout=0.5):
                    self.assertTrue(second_finished.wait(timeout=5))
                release_first_read.set()
                first.join(timeout=5)
                second.join(timeout=5)

                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertEqual(first.exitcode, 0)
                self.assertEqual(second.exitcode, 0)
                self.assertEqual(
                    [results.get(timeout=2) for _ in range(2)], ["ok", "ok"]
                )
                text = (repo / ".manageroo" / "PROJECT-MEMORY.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Concurrent shipped item.", text)
                self.assertIn("Concurrent operator note.", text)
            finally:
                release_first_read.set()
                for process in (first, second):
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

    def test_project_memory_refuses_symlinked_manageroo_parent_without_external_write(self):
        if os.name == "nt":
            self.skipTest("symlink semantics vary on Windows")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            outside = root / "outside"
            repo.mkdir()
            outside.mkdir()
            (repo / ".manageroo").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(SafetyError):
                ensure_project_memory(repo)

            self.assertFalse((outside / "PROJECT-MEMORY.md").exists())

    def test_create_project_repo_initializes_missing_folder_with_first_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "new-product"
            result = create_project_repo(
                repo,
                title="New Product",
                description="Make the first release less painful.",
            )
            self.assertEqual(Path(result["repo"]), repo.resolve())
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

    def test_existing_git_repo_with_deleted_tracked_file_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "existing-deletion"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("keep this in history\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(
                [
                    "git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-q", "-m", "Existing project",
                ],
                cwd=repo,
                check=True,
            )
            tracked.unlink()
            head_before = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            index_before = subprocess.run(
                ["git", "diff", "--cached", "--name-status"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            status_before = subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout

            with self.assertRaises(ValueError):
                create_project_repo(repo, title="Do Not Scaffold")

            head_after = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            index_after = subprocess.run(
                ["git", "diff", "--cached", "--name-status"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            status_after = subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            self.assertEqual(head_after, head_before)
            self.assertEqual(index_after, index_before)
            self.assertEqual(status_after, status_before)
            self.assertFalse(tracked.exists())
            self.assertFalse((repo / "README.md").exists())

    def test_existing_clean_git_repo_with_hidden_tracked_file_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "existing-hidden-tracked"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("existing project\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(
                [
                    "git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-q", "-m", "Existing project",
                ],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "update-index", "--skip-worktree", "tracked.txt"], cwd=repo, check=True,
            )
            tracked.unlink()
            head_before = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            status_before = subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            self.assertEqual(status_before, "")

            with self.assertRaises(ValueError):
                create_project_repo(repo, title="Do Not Scaffold")

            head_after = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            status_after = subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout
            self.assertEqual(head_after, head_before)
            self.assertEqual(status_after, status_before)
            self.assertFalse(tracked.exists())
            self.assertFalse((repo / "README.md").exists())

    def test_create_project_repo_stages_only_scaffold_created_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "scoped-staging"
            original_scaffold = project_module._scaffold_base_files

            def scaffold_with_operator_file(*args, **kwargs):
                created = original_scaffold(*args, **kwargs)
                (repo / "operator-note.txt").write_text("do not commit\n", encoding="utf-8")
                return created

            with patch.object(
                project_module, "_scaffold_base_files", side_effect=scaffold_with_operator_file,
            ):
                create_project_repo(repo, title="Scoped Staging")

            tracked = subprocess.run(
                ["git", "ls-files"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout.splitlines()
            status = subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo, text=True,
                stdout=subprocess.PIPE, check=True,
            ).stdout.splitlines()
            self.assertIn("README.md", tracked)
            self.assertNotIn("operator-note.txt", tracked)
            self.assertIn("?? operator-note.txt", status)

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

    def test_initialization_preflights_non_utf8_project_memory_before_mutating_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            manageroo = repo / ".manageroo"
            manageroo.mkdir()
            memory = manageroo / "PROJECT-MEMORY.md"
            memory.write_bytes(b"prefix\xffsuffix")
            before = {
                path.relative_to(repo).as_posix(): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }

            with self.assertRaises(ValueError):
                initialize_project(repo, agent="mock")

            after = {
                path.relative_to(repo).as_posix(): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            self.assertEqual(after, before)
            self.assertFalse((manageroo / "config.toml").exists())
            self.assertFalse((manageroo / "PRODUCT-BRIEF.md").exists())

    def test_initialization_rejects_unsafe_product_brief_before_mutating_repo(self):
        unsafe_kinds = ("directory",) if os.name == "nt" else ("dangling-symlink", "directory")
        for unsafe_kind in unsafe_kinds:
            with self.subTest(unsafe_kind=unsafe_kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                repo = root / "repo"
                repo.mkdir()
                subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
                (repo / "README.md").write_text("fixture\n", encoding="utf-8")
                manageroo = repo / ".manageroo"
                manageroo.mkdir()
                brief = manageroo / "PRODUCT-BRIEF.md"
                outside = root / "outside-brief.md"
                if unsafe_kind == "dangling-symlink":
                    brief.symlink_to(outside)
                else:
                    brief.mkdir()

                with self.assertRaises(ValueError):
                    initialize_project(repo, agent="mock")

                self.assertFalse((manageroo / "config.toml").exists())
                self.assertFalse(outside.exists())

    def test_initialization_rejects_existing_external_product_brief_symlink_before_mutating_repo(self):
        if os.name == "nt":
            self.skipTest("symlink semantics vary on Windows")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            manageroo = repo / ".manageroo"
            manageroo.mkdir()
            outside = root / "outside-brief.md"
            sentinel = b"external brief must remain unchanged\n"
            outside.write_bytes(sentinel)
            (manageroo / "PRODUCT-BRIEF.md").symlink_to(outside)

            with self.assertRaises(ValueError):
                initialize_project(repo, agent="mock")

            self.assertEqual(outside.read_bytes(), sentinel)
            self.assertFalse((manageroo / "config.toml").exists())
            self.assertFalse((manageroo / "PROJECT-MEMORY.md").exists())
            self.assertFalse((repo / ".agents").exists())
            self.assertFalse((repo / "AGENTS.md").exists())
            self.assertFalse((repo / "CONTEXT.md").exists())

    def test_initialization_preserves_existing_instruction_context_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            (repo / "AGENTS.md").write_text("# My rules\n\nKeep this rule.\n", encoding="utf-8")
            (repo / "CONTEXT.md").write_text("# My context\n\nKeep this language.\n", encoding="utf-8")

            initialize_project(repo, agent="mock")
            initialize_project(repo, agent="mock")

            agents_text = (repo / "AGENTS.md").read_text(encoding="utf-8")
            context_text = (repo / "CONTEXT.md").read_text(encoding="utf-8")
            self.assertIn("Keep this rule.", agents_text)
            self.assertIn("Keep this language.", context_text)
            self.assertEqual(agents_text.count("<!-- MANAGEROO:BEGIN -->"), 1)
            self.assertEqual(context_text.count("<!-- MANAGEROO-CONTEXT:BEGIN -->"), 1)

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
