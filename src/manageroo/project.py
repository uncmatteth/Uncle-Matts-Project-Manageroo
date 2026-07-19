from __future__ import annotations

import json
import shutil
from html import escape
from pathlib import Path

from .assets import asset_path
from .config import write_config
from .detector import detect_gates
from .errors import ConfigurationError
from .project_memory import ensure_project_memory
from .runner import CommandRunner
from .util import atomic_write_json, atomic_write_text

AGENTS_BLOCK = """\
<!-- MANAGEROO:BEGIN -->
## MANAGEROO

For non-trivial product construction, repair, or refactoring, use the
`uncle-matts-project-manageroo` skill and run the local `manageroo` controller.

The controller, not an agent, owns phase transitions, task scope, context budgets,
verification gates, review acceptance, and completion status.

Agents must never:
- edit `.manageroo/config.toml` or locked run artifacts;
- commit, push, switch branches, or modify `.git`;
- weaken acceptance tests to obtain a passing result;
- claim completion without a `COMPLETE` controller state.

Capture newly discovered product ideas with `manageroo idea add "..."` rather than
silently broadening the current task.

Read `.manageroo/PROJECT-MEMORY.md` before broad product work. Preserve the
`What Must Not Break` section unless the operator explicitly changes it.

Read `.manageroo/intent/INTENT-LOCK.md` before relying on a compacted chat,
handoff, or old summary. If a summary drops a must-not rule, rejected idea,
latest correction, proof requirement, or scope boundary, stop and run
`manageroo compact audit --summary SUMMARY.md`.

Use relevant installed skills when their triggers match, but do not treat host-owned
skills as Manageroo-owned dependencies. Manageroo's portable core remains bounded.
<!-- MANAGEROO:END -->
"""

CONTEXT_BLOCK = """\
<!-- MANAGEROO-CONTEXT:BEGIN -->
## MANAGEROO Project Context

This file is optional human-readable project context. The user does not need to
understand agent memory files by hand.

For broad work, agents and AI IDEs should read these in order:

1. `.manageroo/PROJECT-MEMORY.md` for durable project identity, shipped facts,
   must-not-break rules, proof, and operator notes.
2. `.manageroo/intent/INTENT-LOCK.md` for the current ask, must-not rules,
   rejected ideas, latest corrections, proof, and scope boundaries.
3. `.manageroo/PRODUCT-BRIEF.md` for the current requested build or repair.
4. `AGENTS.md` for repo operating rules.
5. This `CONTEXT.md` file when the repo has extra background, product language,
   audience notes, or document/prose instructions.

If long prose, PDFs, screenshots, transcripts, or exact wording matter, use the
document/prose lane. Do not silently paraphrase exact user text or pretend media
metadata is real vision.

If chat compaction or a handoff is involved, run
`manageroo compact audit --summary SUMMARY.md` before treating the summary as authoritative.
<!-- MANAGEROO-CONTEXT:END -->
"""

STARTER_TEMPLATES = {
    "blank": "Minimal README and .gitignore only.",
    "static-site": "Simple static homepage with CSS and a no-dependency unittest smoke check.",
    "python-cli": "Small Python CLI entrypoint with a no-dependency unittest smoke check.",
    "docs-project": "Markdown planning/release docs with a no-dependency unittest smoke check.",
}


def git_root(path: Path) -> Path:
    runner = CommandRunner()
    result = runner.run(["git", "rev-parse", "--show-toplevel"], cwd=path, timeout_seconds=30)
    if not result.passed:
        raise ConfigurationError("MANAGEROO requires an existing Git repository. Initialize and commit/import the project first.")
    return Path(result.stdout.strip()).resolve()


def _run_git(runner: CommandRunner, argv: list[str], cwd: Path) -> str:
    result = runner.run(["git", *argv], cwd=cwd, timeout_seconds=300)
    if not result.passed:
        raise ConfigurationError(result.stderr or f"Git command failed: git {' '.join(argv)}")
    return result.stdout.strip()


def _has_entries(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _non_git_entries(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [entry for entry in path.iterdir() if entry.name != ".git"]


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            break
        current = current.parent
    return current


def starter_choices() -> list[str]:
    return sorted(STARTER_TEMPLATES)


def _safe_text(value: str, fallback: str) -> str:
    cleaned = " ".join(value.strip().split())
    return cleaned or fallback


def _starter_files(starter: str, display_name: str, description: str) -> dict[str, str]:
    description = _safe_text(description, "Describe what this product should become.")
    if starter == "blank":
        return {}
    if starter == "static-site":
        html_title = escape(display_name)
        html_description = escape(description)
        return {
            "index.html": "\n".join([
                "<!doctype html>", '<html lang="en">', "<head>", '  <meta charset="utf-8">',
                '  <meta name="viewport" content="width=device-width, initial-scale=1">',
                f"  <title>{html_title}</title>", '  <link rel="stylesheet" href="styles.css">', "</head>", "<body>",
                '  <main class="shell">', f"    <h1>{html_title}</h1>", f"    <p>{html_description}</p>",
                '    <a href="mailto:hello@example.com">Contact</a>', "  </main>", "</body>", "</html>", "",
            ]),
            "styles.css": "\n".join([
                ":root {", "  color-scheme: light dark;", "  font-family: Arial, sans-serif;", "}", "",
                "body {", "  margin: 0;", "  min-height: 100vh;", "  display: grid;", "  place-items: center;", "  padding: 24px;", "}", "",
                ".shell {", "  max-width: 720px;", "}", "",
            ]),
            "tests/__init__.py": "",
            "tests/test_static_site.py": "\n".join([
                "from pathlib import Path", "import unittest", "", "ROOT = Path(__file__).resolve().parents[1]", "", "",
                "class StaticSiteSmokeTests(unittest.TestCase):",
                "    def test_homepage_has_required_structure(self):",
                "        html = (ROOT / 'index.html').read_text(encoding='utf-8').lower()",
                "        self.assertIn('<title>', html)", "        self.assertIn('<main', html)", "        self.assertIn('<h1>', html)",
                "        self.assertTrue((ROOT / 'styles.css').exists())", "", "", "if __name__ == '__main__':", "    unittest.main()", "",
            ]),
        }
    if starter == "python-cli":
        return {
            "app.py": "\n".join([
                "from __future__ import annotations", "", "", "def describe() -> str:", f"    return {description!r}", "", "",
                "def main() -> int:", "    print(describe())", "    return 0", "", "", "if __name__ == '__main__':", "    raise SystemExit(main())", "",
            ]),
            "tests/__init__.py": "",
            "tests/test_app.py": "\n".join([
                "import sys", "from pathlib import Path", "import unittest", "", "ROOT = Path(__file__).resolve().parents[1]",
                "sys.path.insert(0, str(ROOT))", "import app", "", "", "class AppSmokeTests(unittest.TestCase):",
                "    def test_describe_returns_product_text(self):", "        self.assertTrue(app.describe().strip())", "", "",
                "if __name__ == '__main__':", "    unittest.main()", "",
            ]),
        }
    if starter == "docs-project":
        return {
            "docs/PROJECT.md": "\n".join([
                f"# {display_name}", "", description, "", "## Current Goal", "", "- Describe the first useful release.", "",
                "## Open Questions", "", "- What must be true before release?", "",
            ]),
            "docs/RELEASE_CHECKLIST.md": "\n".join([
                "# Release Checklist", "", "- [ ] Product brief is current.", "- [ ] Verification checks pass.",
                "- [ ] Rollback plan is written.", "- [ ] Human approval is recorded.", "",
            ]),
            "tests/__init__.py": "",
            "tests/test_docs.py": "\n".join([
                "from pathlib import Path", "import unittest", "", "ROOT = Path(__file__).resolve().parents[1]", "", "",
                "class DocsSmokeTests(unittest.TestCase):", "    def test_release_checklist_exists(self):",
                "        checklist = ROOT / 'docs' / 'RELEASE_CHECKLIST.md'", "        self.assertTrue(checklist.exists())",
                "        self.assertIn('Rollback plan', checklist.read_text(encoding='utf-8'))", "", "", "if __name__ == '__main__':", "    unittest.main()", "",
            ]),
        }
    raise ValueError(f"Unknown starter {starter!r}. Use one of: {', '.join(starter_choices())}.")


def _write_starter_files(target: Path, starter: str, display_name: str, description: str) -> list[str]:
    created: list[str] = []
    for relative, text in _starter_files(starter, display_name, description).items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            continue
        atomic_write_text(path, text)
        created.append(relative)
    return created


def _scaffold_base_files(target: Path, display_name: str, description: str, starter: str) -> list[str]:
    created_files: list[str] = []
    readme = target / "README.md"
    if not readme.exists():
        atomic_write_text(readme, "\n".join([f"# {display_name}", "", description, "", "Created with MANAGEROO Solo Operator Mode.", ""]))
        created_files.append("README.md")
    gitignore = target / ".gitignore"
    if not gitignore.exists():
        atomic_write_text(gitignore, "\n".join([
            "# MANAGEROO transient evidence", ".manageroo/runs/", ".manageroo/cache/", "",
            "# Local environment files", ".env", ".env.*", "__pycache__/", ".venv/", "",
        ]))
        created_files.append(".gitignore")
    created_files.extend(_write_starter_files(target, starter, display_name, description))
    return created_files


def create_project_repo(path: Path, *, title: str = "", description: str = "", starter: str = "blank") -> dict:
    target = path.expanduser().resolve()
    starter = starter.strip().lower() or "blank"
    if starter not in STARTER_TEMPLATES:
        raise ValueError(f"Unknown starter {starter!r}. Use one of: {', '.join(starter_choices())}.")
    runner = CommandRunner()
    if target.exists() and not target.is_dir():
        raise ValueError(f"Refusing to create project over a file: {target}")

    existing_git = False
    if target.exists():
        try:
            root = git_root(target)
        except ConfigurationError:
            root = None
        if root is not None:
            if root != target:
                raise ValueError(f"Refusing to create inside another Git repository: {target}")
            existing_git = True
            requested_scaffold = starter != "blank" or bool(title.strip()) or bool(description.strip())
            if not requested_scaffold:
                return {"status": "already-git", "repo": str(root), "initial_commit": "", "created_files": []}
            if _non_git_entries(target):
                raise ValueError(
                    "Starter/title/description options were supplied for an existing non-empty Git repository. "
                    "Refusing to scaffold over existing project files."
                )
        elif _has_entries(target):
            raise ValueError(f"Refusing to initialize non-empty non-Git folder: {target}. Run `git init` there yourself if you want to adopt existing files.")
    else:
        parent = _nearest_existing_parent(target.parent)
        try:
            root = git_root(parent)
        except ConfigurationError:
            root = None
        if root is not None:
            raise ValueError(f"Refusing to create nested Git repository inside {root}: {target}")

    target.mkdir(parents=True, exist_ok=True)
    display_name = title.strip() or target.name.replace("-", " ").replace("_", " ").title()
    description = description.strip() or "Describe what this product should become."
    created_files = _scaffold_base_files(target, display_name, description, starter)

    if not existing_git:
        _run_git(runner, ["init", "-b", "main"], target)
    _run_git(runner, ["add", "."], target)
    status = _run_git(runner, ["status", "--porcelain"], target)
    initial_commit = ""
    if status:
        result = runner.run([
            "git", "-c", "user.name=MANAGEROO Controller", "-c", "user.email=manageroo@local.invalid",
            "commit", "-m", "Initial product scaffold",
        ], cwd=target, timeout_seconds=300)
        if not result.passed:
            raise ConfigurationError(result.stderr or "Could not create initial product commit.")
        initial_commit = _run_git(runner, ["rev-parse", "HEAD"], target)
    return {
        "status": "scaffolded-existing-git" if existing_git else "created",
        "repo": str(target), "initial_commit": initial_commit, "starter": starter, "created_files": created_files,
    }


def _append_managed_block(
    path: Path,
    block: str,
    *,
    heading: str = "# Agent operating guide\n\n",
    marker: str = "<!-- MANAGEROO:BEGIN -->",
) -> None:
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Refusing to rewrite non-UTF-8 instruction file: {path}") from exc
        if marker in text:
            return
        if text and not text.endswith("\n"):
            text += "\n"
        atomic_write_text(path, text + "\n" + block)
    else:
        atomic_write_text(path, heading + block)


def initialize_project(
    repo: Path,
    agent: str = "codex",
    *,
    project_summary: str = "",
    must_not: list[str] | None = None,
    proof: list[str] | None = None,
) -> dict:
    repo = git_root(repo)
    gates = detect_gates(repo)
    manageroo = repo / ".manageroo"
    manageroo.mkdir(parents=True, exist_ok=True)
    (manageroo / "ideas").mkdir(exist_ok=True)
    (manageroo / "runs").mkdir(exist_ok=True)

    config_path = write_config(repo, agent, gates)
    brief_path = manageroo / "PRODUCT-BRIEF.md"
    if not brief_path.exists():
        shutil.copy2(asset_path("templates/PRODUCT-BRIEF.md"), brief_path)
    memory_result = ensure_project_memory(repo, project_summary=project_summary, must_not=must_not, proof=proof)

    skill_destination = repo / ".agents" / "skills" / "uncle-matts-project-manageroo" / "SKILL.md"
    skill_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(asset_path("skills/uncle-matts-project-manageroo/SKILL.md"), skill_destination)

    _append_managed_block(repo / "AGENTS.md", AGENTS_BLOCK)
    _append_managed_block(repo / "CONTEXT.md", CONTEXT_BLOCK, heading="# Project context\n\n", marker="<!-- MANAGEROO-CONTEXT:BEGIN -->")

    gitignore = repo / ".gitignore"
    additions = [".manageroo/runs/", ".manageroo/cache/"]
    if gitignore.exists():
        try:
            current = gitignore.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Refusing to rewrite non-UTF-8 .gitignore: {gitignore}") from exc
    else:
        current = ""
    missing = [item for item in additions if item not in current.splitlines()]
    if missing:
        if current and not current.endswith("\n"):
            current += "\n"
        current += "\n# MANAGEROO transient evidence\n" + "\n".join(missing) + "\n"
        atomic_write_text(gitignore, current)

    result = {
        "repo": str(repo), "config": str(config_path), "brief": str(brief_path), "memory": memory_result["path"],
        "context": str(repo / "CONTEXT.md"), "skill": str(skill_destination), "detected_gates": gates,
        "warning": None if gates else "No deterministic project gate was detected. Add at least one [[verification.gates]] entry before a real run.",
    }
    atomic_write_json(manageroo / "init-report.json", result)
    return result
