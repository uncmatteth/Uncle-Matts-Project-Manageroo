from __future__ import annotations

from pathlib import Path
from typing import Callable

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
    selected_agent = agent or "auto"
    if not interactive:
        return {
            "repo": Path(repo) if repo is not None else Path("."),
            "agent": selected_agent,
            "integrations": {name: False for name in INTEGRATIONS},
        }

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


def collect_solo_answers(
    *,
    repo: str | Path | None,
    agent: str | None,
    want: str,
    audience: str,
    outcomes: list[str],
    must_not: list[str],
    proof: list[str],
    stop: str,
    later: list[str],
    mode: str,
    run: bool | None,
    integrations: dict[str, bool],
    interactive: bool,
    input_fn: InputFn = input,
    output_fn: OutputFn | None = print,
) -> dict:
    selected_agent = agent or "auto"
    if not interactive:
        return {
            "repo": Path(repo) if repo is not None else Path("."),
            "agent": selected_agent,
            "want": want,
            "audience": audience,
            "outcomes": outcomes,
            "must_not": must_not,
            "proof": proof,
            "stop": stop,
            "later": later,
            "mode": mode,
            "run": bool(run),
            "integrations": integrations,
        }

    selected_repo = Path(
        str(repo)
        if repo is not None
        else _ask_text(
            "Which project folder should your solo product team work on?",
            default=".",
            input_fn=input_fn,
            output_fn=output_fn,
        )
    )
    selected_want = want or _ask_text(
        "What do you want built or fixed?",
        default="",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    selected_audience = audience or _ask_text(
        "Who is this for?",
        default="The people or systems that use this repo.",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    selected_outcomes = list(outcomes)
    if not selected_outcomes:
        answer = _ask_text(
            "What visible result should be true when this works?",
            default="",
            input_fn=input_fn,
            output_fn=output_fn,
        )
        if answer:
            selected_outcomes.append(answer)
    selected_must_not = list(must_not)
    if not selected_must_not:
        answer = _ask_text(
            "What must not break or be touched?",
            default="Do not break existing working behavior.",
            input_fn=input_fn,
            output_fn=output_fn,
        )
        if answer:
            selected_must_not.append(answer)
    selected_proof = list(proof)
    if not selected_proof:
        answer = _ask_text(
            "What check, demo, or proof should verify it?",
            default="Run the repo's configured checks and report the result.",
            input_fn=input_fn,
            output_fn=output_fn,
        )
        if answer:
            selected_proof.append(answer)
    selected_stop = stop or _ask_text(
        "When should the agent stop instead of guessing?",
        default="Stop after two failed repair passes and report the blocker.",
        input_fn=input_fn,
        output_fn=output_fn,
    )
    selected_mode = _ask_choice(
        "Build new behavior or repair broken behavior?",
        choices=["build", "repair"],
        default=mode,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    selected_integrations = {
        name: integrations.get(name, False)
        for name in INTEGRATIONS
    }
    for name, prompt in INTEGRATIONS.items():
        if selected_integrations[name]:
            continue
        selected_integrations[name] = _ask_yes_no(
            prompt,
            default=False,
            input_fn=input_fn,
            output_fn=output_fn,
        )
    should_run = run if run is not None else _ask_yes_no(
        "Run the build/repair now if readiness passes?",
        default=False,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    return {
        "repo": selected_repo,
        "agent": selected_agent,
        "want": selected_want,
        "audience": selected_audience,
        "outcomes": selected_outcomes,
        "must_not": selected_must_not,
        "proof": selected_proof,
        "stop": selected_stop,
        "later": later,
        "mode": selected_mode,
        "run": bool(should_run),
        "integrations": selected_integrations,
    }


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
