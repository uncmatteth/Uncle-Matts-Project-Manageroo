from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .branding import PROJECT_DIR
from .cli import main as cli_main
from .cli import parser as cli_parser
from .config import AGENT_PRESETS
from .discovery_policy import decisions_fully_resolved, render_blocking_questions
from .prove import LIVE_AGENT_CHOICES, format_product_proof, run_product_proof
from .system_capacity import format_capacity, host_capacity
from .util import atomic_write_json, read_json, utc_now


def _auto_live_agent() -> str | None:
    for name in LIVE_AGENT_CHOICES:
        executable = str(AGENT_PRESETS.get(name, {}).get("executable") or "")
        if executable and shutil.which(executable):
            return name
    return None


def _provider_neutral_argv(argv: list[str]) -> list[str]:
    explicit_agent = any(
        value == "--agent" or value.startswith("--agent=")
        for value in argv
    )
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
        description=(
            "Inspect the current machine and print Manageroo's conservative capacity profile."
        ),
    )
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    profile = host_capacity(Path(args.repo))
    rendered = (
        json.dumps(profile, indent=2, sort_keys=True)
        if args.json
        else format_capacity(profile)
    )
    print(rendered, end="\n" if args.json else "")
    return 0


def _run_root(repo: Path, run_id: str) -> Path:
    return repo.expanduser().resolve() / PROJECT_DIR / "runs" / run_id


def _blocking_decisions(run_root: Path) -> list[dict]:
    if decisions_fully_resolved(run_root):
        return []
    path = run_root / "artifacts" / "planning" / "blocking-decisions.json"
    if not path.is_file():
        return []
    payload = read_json(path)
    return list(payload.get("decisions", []) or [])


def _decisions_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo decisions",
        description=(
            "Show or answer high-impact product decisions that Manageroo could not safely infer."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("show", "answer"):
        item = sub.add_parser(command)
        item.add_argument("run_id")
        item.add_argument("--repo", default=".")
        if command == "show":
            item.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    run_root = _run_root(Path(args.repo), args.run_id)
    decisions = _blocking_decisions(run_root)
    if not decisions:
        print("No unresolved blocking decisions were found for that run.")
        return 1

    if args.command == "show":
        if args.json:
            print(json.dumps({"run_id": args.run_id, "decisions": decisions}, indent=2))
        else:
            markdown = render_blocking_questions(run_root)
            text = (
                markdown.read_text(encoding="utf-8")
                if markdown
                else "No blocking questions found."
            )
            print(text, end="")
        return 0

    answers: list[dict[str, str]] = []
    for index, decision in enumerate(decisions, 1):
        question = str(decision.get("question") or f"Decision {index}")
        why = str(decision.get("why") or "")
        options = [str(item) for item in decision.get("options", [])]
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
    print(
        f"Next: manageroo run --continue {args.run_id} "
        f"--repo {repo} --apply"
    )
    return 0


def _root_help() -> str:
    base = cli_parser().format_help().rstrip()
    return (
        base
        + "\n\nProduct certification:\n"
        + "  prove                 Run adversarial end-to-end Manageroo product proof.\n"
        + "                        Uses any available supported live coding agent.\n"
        + "\nDiscovery and capacity:\n"
        + "  capacity              Inspect CPU, RAM, GPU/VRAM, disk, and worker concurrency.\n"
        + "  decisions             Show or answer high-impact questions surfaced during a run.\n"
    )


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "prove":
        return _prove_main(argv[1:])
    if argv and argv[0] == "capacity":
        return _capacity_main(argv[1:])
    if argv and argv[0] == "decisions":
        return _decisions_main(argv[1:])
    if argv in (["--help"], ["-h"]):
        print(_root_help(), end="")
        return 0
    return cli_main(_provider_neutral_argv(argv))
