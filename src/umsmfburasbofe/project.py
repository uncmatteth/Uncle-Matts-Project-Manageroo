from __future__ import annotations

import json
import shutil
from pathlib import Path

from .assets import asset_path
from .config import write_config
from .detector import detect_gates
from .errors import ConfigurationError
from .runner import CommandRunner
from .util import atomic_write_json, atomic_write_text


AGENTS_BLOCK = """\
<!-- UMSMFBURASBOFE:BEGIN -->
## UMSMFBURASBOFE — Ultimate Remix All-Star Booty of Fire Edition

For non-trivial product construction, repair, or refactoring, use the
`uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition` skill and run the local `umsmfburasbofe` controller.

The controller, not an agent, owns phase transitions, task scope, context budgets,
verification gates, review acceptance, and completion status.

Agents must never:
- edit `.umsmfburasbofe/config.toml` or locked run artifacts;
- commit, push, switch branches, or modify `.git`;
- weaken acceptance tests to obtain a passing result;
- claim completion without a `COMPLETE` controller state.

Capture newly discovered product ideas with `umsmfburasbofe idea add "..."` rather than
silently broadening the current task.
<!-- UMSMFBURASBOFE:END -->
"""


def git_root(path: Path) -> Path:
    runner = CommandRunner()
    result = runner.run(["git", "rev-parse", "--show-toplevel"], cwd=path, timeout_seconds=30)
    if not result.passed:
        raise ConfigurationError(
            "UMSMFBURASBOFE requires an existing Git repository. Initialize and commit/import the project first."
        )
    return Path(result.stdout.strip()).resolve()


def _run_git(runner: CommandRunner, argv: list[str], cwd: Path) -> str:
    result = runner.run(["git", *argv], cwd=cwd, timeout_seconds=300)
    if not result.passed:
        raise ConfigurationError(result.stderr or f"Git command failed: git {' '.join(argv)}")
    return result.stdout.strip()


def _has_entries(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            break
        current = current.parent
    return current


def create_project_repo(
    path: Path,
    *,
    title: str = "",
    description: str = "",
) -> dict:
    target = path.expanduser().resolve()
    runner = CommandRunner()
    if target.exists() and not target.is_dir():
        raise ValueError(f"Refusing to create project over a file: {target}")
    if target.exists():
        try:
            root = git_root(target)
        except ConfigurationError:
            root = None
        if root is not None:
            if root != target:
                raise ValueError(f"Refusing to create inside another Git repository: {target}")
            return {"status": "already-git", "repo": str(root), "initial_commit": ""}
        if _has_entries(target):
            raise ValueError(
                f"Refusing to initialize non-empty non-Git folder: {target}. "
                "Run `git init` there yourself if you want to adopt existing files."
            )
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
    readme = target / "README.md"
    if not readme.exists():
        atomic_write_text(
            readme,
            "\n".join(
                [
                    f"# {display_name}",
                    "",
                    description,
                    "",
                    "Created with UMSMFBURASBOFE Solo Operator Mode.",
                    "",
                ]
            ),
        )
    gitignore = target / ".gitignore"
    if not gitignore.exists():
        atomic_write_text(
            gitignore,
            "\n".join(
                [
                    "# UMSMFBURASBOFE transient evidence",
                    ".umsmfburasbofe/runs/",
                    ".umsmfburasbofe/cache/",
                    "",
                    "# Local environment files",
                    ".env",
                    ".env.*",
                    "__pycache__/",
                    ".venv/",
                    "",
                ]
            ),
        )

    _run_git(runner, ["init", "-b", "main"], target)
    _run_git(runner, ["add", "README.md", ".gitignore"], target)
    result = runner.run(
        [
            "git",
            "-c",
            "user.name=UMSMFBURASBOFE Controller",
            "-c",
            "user.email=umsmfburasbofe@local.invalid",
            "commit",
            "-m",
            "Initial product scaffold",
        ],
        cwd=target,
        timeout_seconds=300,
    )
    if not result.passed:
        raise ConfigurationError(result.stderr or "Could not create initial product commit.")
    initial_commit = _run_git(runner, ["rev-parse", "HEAD"], target)
    return {"status": "created", "repo": str(target), "initial_commit": initial_commit}


def _append_managed_block(path: Path, block: str) -> None:
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        if "<!-- UMSMFBURASBOFE:BEGIN -->" in text:
            return
        if text and not text.endswith("\n"):
            text += "\n"
        atomic_write_text(path, text + "\n" + block)
    else:
        atomic_write_text(path, "# Agent operating guide\n\n" + block)


def initialize_project(repo: Path, agent: str = "codex") -> dict:
    repo = git_root(repo)
    gates = detect_gates(repo)
    umsmfburasbofe = repo / ".umsmfburasbofe"
    umsmfburasbofe.mkdir(parents=True, exist_ok=True)
    (umsmfburasbofe / "ideas").mkdir(exist_ok=True)
    (umsmfburasbofe / "runs").mkdir(exist_ok=True)

    config_path = write_config(repo, agent, gates)
    brief_path = umsmfburasbofe / "PRODUCT-BRIEF.md"
    if not brief_path.exists():
        shutil.copy2(asset_path("templates/PRODUCT-BRIEF.md"), brief_path)

    skill_destination = (
        repo / ".agents" / "skills" / "uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition" / "SKILL.md"
    )
    skill_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        asset_path("skills/uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition/SKILL.md"),
        skill_destination,
    )

    _append_managed_block(repo / "AGENTS.md", AGENTS_BLOCK)

    gitignore = repo / ".gitignore"
    additions = [".umsmfburasbofe/runs/", ".umsmfburasbofe/cache/"]
    current = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.exists() else ""
    missing = [item for item in additions if item not in current.splitlines()]
    if missing:
        if current and not current.endswith("\n"):
            current += "\n"
        current += "\n# UMSMFBURASBOFE transient evidence\n" + "\n".join(missing) + "\n"
        atomic_write_text(gitignore, current)

    result = {
        "repo": str(repo),
        "config": str(config_path),
        "brief": str(brief_path),
        "skill": str(skill_destination),
        "detected_gates": gates,
        "warning": None if gates else (
            "No deterministic project gate was detected. Add at least one "
            "[[verification.gates]] entry before a real run."
        ),
    }
    atomic_write_json(umsmfburasbofe / "init-report.json", result)
    return result
