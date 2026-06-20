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
    claude = repo / "CLAUDE.md"
    if not claude.exists():
        atomic_write_text(claude, "@AGENTS.md\n")

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
