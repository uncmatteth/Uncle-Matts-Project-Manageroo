from __future__ import annotations

import argparse
import json
import sys

from .cli import main as cli_main
from .cli import parser as cli_parser
from .prove import format_product_proof, run_product_proof


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
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_product_proof(include_regression=not args.no_regression)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_product_proof(report), end="")
    return 0 if report.get("ok") else 2


def _root_help() -> str:
    base = cli_parser().format_help().rstrip()
    return (
        base
        + "\n\nProduct certification:\n"
        + "  prove                 Run adversarial end-to-end Manageroo product proof.\n"
        + "                        COMPLETE is allowed only when every required lane passes.\n"
    )


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "prove":
        return _prove_main(argv[1:])
    if argv in (["--help"], ["-h"]):
        print(_root_help(), end="")
        return 0
    return cli_main(argv)
