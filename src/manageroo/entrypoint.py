from __future__ import annotations

import argparse
import json
import shutil
import sys

from .cli import main as cli_main
from .cli import parser as cli_parser
from .config import AGENT_PRESETS
from .prove import LIVE_AGENT_CHOICES, format_product_proof, run_product_proof


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


def _root_help() -> str:
    base = cli_parser().format_help().rstrip()
    return (
        base
        + "\n\nProduct certification:\n"
        + "  prove                 Run adversarial end-to-end Manageroo product proof.\n"
        + "                        Uses any available supported live coding agent.\n"
    )


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "prove":
        return _prove_main(argv[1:])
    if argv in (["--help"], ["-h"]):
        print(_root_help(), end="")
        return 0
    return cli_main(_provider_neutral_argv(argv))
