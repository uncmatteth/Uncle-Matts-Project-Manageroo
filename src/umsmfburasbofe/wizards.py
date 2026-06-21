from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import AGENT_PRESETS

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]

INTEGRATIONS = {
    "gbrain": "Use GBrain memory/source mapping?",
    "gitnexus": "Use GitNexus code graph context?",
    "obsidian": "Use Obsidian notes?",
    "loop_library": "Use Matthew Berman / Forward Future Loop Library?",
}


def _say(output_fn: OutputFn | None, message: str) -> None:
    if output_fn:
        output_fn(message)


def _ask_text(
    prompt: str,
    *,
    default: str,
    input_fn: InputFn,
    output_fn: OutputFn | None,
) -> str:
    suffix = f" [{default}]" if default else ""
    _say(output_fn, f"{prompt}{suffix}")
    answer = input_fn("> ").strip()
    return answer or default


def _ask_yes_no(
    prompt: str,
    *,
    default: bool,
    input_fn: InputFn,
    output_fn: OutputFn | None,
) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        _say(output_fn, f"{prompt}{suffix}")
        answer = input_fn("> ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        _say(output_fn, "Answer yes or no.")


def _ask_choice(
    prompt: str,
    *,
    choices: list[str],
    default: str,
    input_fn: InputFn,
    output_fn: OutputFn | None,
) -> str:
    available = ", ".join(choices)
    while True:
        value = _ask_text(
            f"{prompt} ({available})",
            default=default,
            input_fn=input_fn,
            output_fn=output_fn,
        )
        if value in choices:
            return value
        _say(output_fn, f"Use one of: {available}")


def collect_setup_answers(
    *,
    repo: str | Path | None,
    agent: str | None,
    interactive: bool,
    input_fn: InputFn = input,
    output_fn: OutputFn | None = print,
) -> dict:
    if not interactive:
        return {
            "repo": Path(repo) if repo is not None else Path("."),
            "agent": agent or "codex",
            "integrations": {name: False for name in INTEGRATIONS},
        }

    selected_agent = agent or _ask_choice(
        "What AI are you using?",
        choices=sorted(AGENT_PRESETS),
        default="codex",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    selected_repo = Path(
        str(repo)
        if repo is not None
        else _ask_text(
            "What repo do you want to work on?",
            default=".",
            input_fn=input_fn,
            output_fn=output_fn,
        )
    )
    integrations = {
        name: _ask_yes_no(prompt, default=False, input_fn=input_fn, output_fn=output_fn)
        for name, prompt in INTEGRATIONS.items()
    }
    return {"repo": selected_repo, "agent": selected_agent, "integrations": integrations}


def collect_gbrain_answers(
    *,
    source_id: str | None,
    source_path: Path | None,
    apply: bool,
    sync: bool,
    interactive: bool,
    input_fn: InputFn = input,
    output_fn: OutputFn | None = print,
) -> dict:
    if source_id or source_path or not interactive:
        return {
            "source_id": source_id,
            "source_path": source_path,
            "apply": apply,
            "sync": sync,
        }
    if not _ask_yes_no(
        "Add a selected folder to GBrain now?",
        default=False,
        input_fn=input_fn,
        output_fn=output_fn,
    ):
        return {"source_id": None, "source_path": None, "apply": False, "sync": False}
    selected_id = _ask_text(
        "Source id",
        default="my-project",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    selected_path = Path(
        _ask_text(
            "Folder path to map",
            default=".",
            input_fn=input_fn,
            output_fn=output_fn,
        )
    )
    should_sync = _ask_yes_no(
        "Run safe sync after adding it?",
        default=True,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    return {
        "source_id": selected_id,
        "source_path": selected_path,
        "apply": True,
        "sync": should_sync,
    }
