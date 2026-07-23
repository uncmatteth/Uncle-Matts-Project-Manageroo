from __future__ import annotations

import argparse
import json
import shlex
import shutil
import sys
from pathlib import Path

from .branding import PROJECT_DIR
from .clawpatch_batch import batch_fix_open_findings, format_batch_fix
from .cli import main as cli_main
from .cli import parser as cli_parser
from .config import AGENT_PRESETS
from .discovery_policy import decisions_fully_resolved, render_blocking_questions
from .errors import SafetyError
from .host_skills import format_host_skills, inspect_host_skills
from .prove import LIVE_AGENT_CHOICES, format_product_proof, run_product_proof
from .stack_update import STACK_TOOL_NAMES, apply_stack_updates, format_stack_update, stack_update_plan
from .system_capacity import format_capacity, host_capacity
from .util import atomic_write_json, read_json, utc_now


def _auto_live_agent() -> str | None:
    for name in LIVE_AGENT_CHOICES:
        executable = str(AGENT_PRESETS.get(name, {}).get("executable") or "")
        if executable and shutil.which(executable):
            return name
    return None


def _provider_neutral_argv(argv: list[str]) -> list[str]:
    explicit_agent = any(value == "--agent" or value.startswith("--agent=") for value in argv)
    if argv and argv[0] in {"init", "projects"} and not explicit_agent:
        return [*argv, "--agent", "auto"]
    return argv


def _prove_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo prove",
        description="Run adversarial product certification for the Manageroo control plane.",
    )
    parser.add_argument(
        "--no-regression",
        action="store_true",
        help="Skip source regressions. The proof will return PARTIAL, never COMPLETE.",
    )
    parser.add_argument(
        "--live-agent",
        choices=LIVE_AGENT_CHOICES,
        help=(
            "Use a specific live coding-agent preset. Omit this to let Manageroo "
            "select any installed supported worker."
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    selected_agent = args.live_agent or _auto_live_agent()
    report = run_product_proof(
        include_regression=not args.no_regression,
        live_agent=selected_agent,
    )
    report["live_agent_selection"] = (
        "explicit" if args.live_agent else "automatic" if selected_agent else "none-available"
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if selected_agent and not args.live_agent:
            print(f"Auto-selected live agent: {selected_agent}\n")
        print(format_product_proof(report), end="")
    return 0 if report.get("ok") else 2


def _capacity_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo capacity",
        description="Inspect this machine's hardware as informational development-host context.",
    )
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    profile = host_capacity(Path(args.repo))
    rendered = json.dumps(profile, indent=2, sort_keys=True) if args.json else format_capacity(profile)
    print(rendered, end="\n" if args.json else "")
    return 0


def _host_skills_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo host-skills",
        description=(
            "Inspect local agent skill roots without copying, deleting, or claiming ownership of host skills."
        ),
    )
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_host_skills(args.root or None)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_host_skills(report), end="")
    return 0


def _stack_update_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo stack-update",
        description=(
            "Plan or explicitly apply upstream-supported updates for Manageroo's recommended surrounding stack."
        ),
    )
    parser.add_argument(
        "tools",
        nargs="*",
        choices=STACK_TOOL_NAMES,
        help="Optionally limit the operation to one or more named stack tools.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    selected = args.tools or None
    report = apply_stack_updates(selected) if args.apply else stack_update_plan(selected)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_stack_update(report), end="")
    return 0 if report.get("ok") else 2


def _clawpatch_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo clawpatch",
        description=(
            "Run Manageroo-owned cross-platform Clawpatch workflows without shell or PowerShell parsing loops."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    fix_open = sub.add_parser(
        "fix-open",
        description=(
            "Read only Clawpatch findings with status=open, fix them one at a time, and stop fail-closed on the first failure."
        ),
    )
    fix_open.add_argument("--repo", default=".")
    fix_open.add_argument("--limit", type=int, default=0, help="Maximum findings to process; 0 means all open findings.")
    fix_open.add_argument("--apply", action="store_true", help="Actually run fixes. Without this flag, print the plan only.")
    fix_open.add_argument("--no-commit", action="store_true", help="Do not create one Git commit per successful finding.")
    fix_open.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command != "fix-open":
        parser.error("Unknown Clawpatch command.")
    if args.limit < 0:
        parser.error("--limit must be 0 or greater.")
    try:
        report = batch_fix_open_findings(
            Path(args.repo),
            apply=args.apply,
            limit=args.limit,
            commit_each=not args.no_commit,
        )
    except SafetyError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"CLAWPATCH OPEN-FINDING REPAIR: STOPPED\n{exc}")
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_batch_fix(report), end="")
    return 0 if report.get("ok") else 2


def _run_root(repo: Path, run_id: str) -> Path:
    value = str(run_id).strip()
    candidate = Path(value)
    if not value or candidate.is_absolute() or len(candidate.parts) != 1 or value in {".", ".."}:
        raise SafetyError(f"Invalid run id: {run_id!r}")
    base = repo.expanduser().resolve() / PROJECT_DIR / "runs"
    resolved = (base / value).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise SafetyError(f"Run id escapes repository run directory: {run_id!r}") from exc
    return resolved


def _blocking_decisions(run_root: Path) -> list[dict]:
    if decisions_fully_resolved(run_root):
        return []
    path = run_root / "artifacts" / "planning" / "blocking-decisions.json"
    if not path.is_file():
        return []
    payload = read_json(path)
    return list(payload.get("decisions", []) or [])


def _validated_decisions(decisions: list[dict]) -> tuple[list[dict], str | None]:
    validated: list[dict] = []
    for index, decision in enumerate(decisions, 1):
        if not isinstance(decision, dict):
            return [], f"Decision {index} is not an object."
        decision_id = str(decision.get("id") or "").strip()
        options_value = decision.get("options")
        if not decision_id:
            return [], f"Decision {index} has no id."
        if not isinstance(options_value, list) or not options_value:
            return [], f"Decision {decision_id!r} has no selectable options."
        options = [str(item).strip() for item in options_value if str(item).strip()]
        if not options:
            return [], f"Decision {decision_id!r} has no selectable options."
        item = dict(decision)
        item["options"] = options
        validated.append(item)
    return validated, None


def _decisions_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo decisions",
        description="Show or answer high-impact product decisions that Manageroo could not safely infer.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("show", "answer"):
        item = sub.add_parser(command)
        item.add_argument("run_id")
        item.add_argument("--repo", default=".")
        if command == "show":
            item.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_root = _run_root(Path(args.repo), args.run_id)
    except SafetyError as exc:
        parser.error(str(exc))
    decisions = _blocking_decisions(run_root)
    if not decisions:
        if args.command == "show" and args.json:
            print(json.dumps({"run_id": args.run_id, "decisions": []}, indent=2))
        else:
            print("No unresolved blocking decisions were found for that run.")
        return 1

    if args.command == "show":
        if args.json:
            print(json.dumps({"run_id": args.run_id, "decisions": decisions}, indent=2))
        else:
            markdown = render_blocking_questions(run_root)
            text = markdown.read_text(encoding="utf-8") if markdown else "No blocking questions found."
            print(text, end="")
        return 0

    decisions, validation_error = _validated_decisions(decisions)
    if validation_error:
        print(f"Cannot answer blocking decisions: {validation_error}", file=sys.stderr)
        return 2

    answers: list[dict[str, str]] = []
    for index, decision in enumerate(decisions, 1):
        question = str(decision.get("question") or f"Decision {index}")
        why = str(decision.get("why") or "")
        options = [str(item) for item in decision["options"]]
        recommended = str(decision.get("recommended") or "")
        print(f"\n{index}. {question}")
        if why:
            print(f"Why: {why}")
        for option_index, option in enumerate(options, 1):
            marker = " (recommended)" if recommended and option == recommended else ""
            print(f"  {option_index}) {option}{marker}")
        while True:
            suffix = f" [{options.index(recommended) + 1}]" if recommended in options else ""
            raw = input(f"Choose 1-{len(options)}{suffix}: ").strip()
            if not raw and recommended in options:
                chosen = recommended
                break
            try:
                selected = int(raw)
            except ValueError:
                selected = 0
            if 1 <= selected <= len(options):
                chosen = options[selected - 1]
                break
            print("Choose one of the numbered options.")
        answers.append({"id": str(decision.get("id") or ""), "chosen": chosen})

    resolved = run_root / "artifacts" / "planning" / "resolved-decisions.json"
    atomic_write_json(
        resolved,
        {
            "run_id": args.run_id,
            "answered_at": utc_now(),
            "answers": answers,
        },
    )
    repo = Path(args.repo).expanduser().resolve()
    print(f"\nSaved {len(answers)} decision answer(s).")
    print("Next: " + shlex.join(["manageroo", "run", "--continue", args.run_id, "--repo", str(repo), "--apply"]))
    return 0


def _root_help() -> str:
    base = cli_parser().format_help().rstrip()
    return (
        base
        + "\n\nProduct certification:\n"
        + "  prove                 Run adversarial end-to-end Manageroo product proof.\n"
        + "                        Uses any available supported live coding agent.\n"
        + "\nDiscovery and host context:\n"
        + "  capacity              Inspect host CPU, RAM, GPU/VRAM, and disk as context only.\n"
        + "  decisions             Show or answer high-impact questions surfaced during a run.\n"
        + "  host-skills           Inspect host skills without modifying or owning them.\n"
        + "\nCommand-owned repair automation:\n"
        + "  clawpatch fix-open    Plan or apply every currently open Clawpatch finding serially.\n"
        + "                        Cross-platform; one commit per successful fix by default.\n"
        + "\nRecommended stack maintenance:\n"
        + "  stack-update          Dry-run upstream-supported updates; optionally name tools; pass --apply explicitly.\n"
    )


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "prove":
        return _prove_main(argv[1:])
    if argv and argv[0] == "capacity":
        return _capacity_main(argv[1:])
    if argv and argv[0] == "host-skills":
        return _host_skills_main(argv[1:])
    if argv and argv[0] == "decisions":
        return _decisions_main(argv[1:])
    if argv and argv[0] == "clawpatch":
        return _clawpatch_main(argv[1:])
    if argv and argv[0] == "stack-update":
        return _stack_update_main(argv[1:])
    if argv in (["--help"], ["-h"]):
        print(_root_help(), end="")
        return 0
    return cli_main(_provider_neutral_argv(argv))