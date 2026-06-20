from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .branding import FULL_ACRONYM, PROJECT_DIR, PUBLIC_COMMAND, print_banner
from .chiptune import play_once
from .doctor import doctor
from .errors import UMSMFBURASBOFEError
from .ideas import IdeaInbox
from .orchestrator import Orchestrator
from .project import git_root, initialize_project
from .selftest import run_self_test
from .token_modes import install_token_skills, read_token_mode, set_token_mode
from .util import read_json


def _repo(value: str | None) -> Path:
    return git_root(Path(value or ".").resolve())


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog=PUBLIC_COMMAND,
        description=f"{FULL_ACRONYM} coding-agent control plane.",
    )
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help=f"Install project-local {FULL_ACRONYM} assets.")
    init.add_argument("repo", nargs="?", default=".")
    init.add_argument("--agent", choices=["codex", "mock", "generic"], default="codex")

    doc = sub.add_parser("doctor", help="Validate the local environment without modifying code.")
    doc.add_argument("repo", nargs="?", default=".")
    doc.add_argument("--json", action="store_true")

    run = sub.add_parser("run", help="Run the complete one-request workflow.")
    run.add_argument("--repo", default=".")
    run.add_argument("--brief", required=True)
    run.add_argument("--mode", choices=["build", "repair"], required=True)
    apply_group = run.add_mutually_exclusive_group()
    apply_group.add_argument("--apply", action="store_true")
    apply_group.add_argument("--no-apply", action="store_true")

    status = sub.add_parser("status", help="Show durable state for a run.")
    status.add_argument("run_id")
    status.add_argument("--repo", default=".")

    report = sub.add_parser("report", help="Print the product-level final report.")
    report.add_argument("run_id")
    report.add_argument("--repo", default=".")

    idea = sub.add_parser("idea", help="Capture or list evolving product ideas.")
    idea_sub = idea.add_subparsers(dest="idea_command", required=True)
    idea_add = idea_sub.add_parser("add")
    idea_add.add_argument("text")
    idea_add.add_argument("--category", default="unclassified")
    idea_add.add_argument("--repo", default=".")
    idea_list = idea_sub.add_parser("list")
    idea_list.add_argument("--status")
    idea_list.add_argument("--repo", default=".")

    banner = sub.add_parser("banner", help="Show the animated UMSMFBURASBOFE terminal banner.")
    banner.add_argument("--no-animation", action="store_true")

    music = sub.add_parser("music", help=f"Play the original Atari/NES-style {FULL_ACRONYM} theme.")
    music.add_argument("--cue", choices=["install", "build", "success"], default="install")
    music.add_argument("--variant", type=int, default=69)

    token = sub.add_parser("token-mode", help="Choose token-reduction mode for agent prose.")
    token_sub = token.add_subparsers(dest="token_command", required=True)
    token_set = token_sub.add_parser("set", help="Switch token-reduction mode.")
    token_set.add_argument("mode", choices=["off", "caveman", "curse"])
    token_sub.add_parser("status", help="Show selected token-reduction mode.")
    token_sub.add_parser("install-skills", help="Install bundled caveman token skills.")

    sub.add_parser("self-test", help="Run a deterministic mock end-to-end build.")

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_project(Path(args.repo), agent=args.agent)
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "doctor":
            result = doctor(_repo(args.repo))
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                for check in result["checks"]:
                    print(f"{'PASS' if check['ok'] else 'FAIL'}  {check['name']}: {check['detail']}")
                print("READY" if result["ok"] else "NOT READY")
            return 0 if result["ok"] else 2

        if args.command == "run":
            repo = _repo(args.repo)
            apply_override = True if args.apply else False if args.no_apply else None
            result = Orchestrator(repo).run(
                brief_path=Path(args.brief),
                mode=args.mode,
                apply_on_success=apply_override,
            )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "status":
            repo = _repo(args.repo)
            path = repo / PROJECT_DIR / "runs" / args.run_id / "state.json"
            print(json.dumps(read_json(path), indent=2))
            return 0

        if args.command == "report":
            repo = _repo(args.repo)
            path = repo / PROJECT_DIR / "runs" / args.run_id / "delivery" / "FINAL-REPORT.md"
            print(path.read_text(encoding="utf-8"))
            return 0

        if args.command == "idea":
            repo = _repo(args.repo)
            inbox = IdeaInbox(repo)
            if args.idea_command == "add":
                path = inbox.add(args.text, args.category)
                print(path)
            else:
                print(json.dumps(inbox.list(args.status), indent=2))
            return 0

        if args.command == "banner":
            print_banner(animation=not args.no_animation)
            return 0

        if args.command == "music":
            print_banner(animation=False, compact=True)
            played = play_once(cue=args.cue, variant=args.variant)
            if not played:
                print("No supported host audio player was detected; music was skipped.")
                return 2
            return 0

        if args.command == "token-mode":
            if args.token_command == "set":
                print(json.dumps(set_token_mode(args.mode), indent=2))
                return 0
            if args.token_command == "install-skills":
                print(json.dumps({"installed_skills": install_token_skills()}, indent=2))
                return 0
            print(json.dumps(read_token_mode(), indent=2))
            return 0

        if args.command == "self-test":
            result = run_self_test()
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 3

        return 1
    except (UMSMFBURASBOFEError, OSError, ValueError, RuntimeError) as exc:
        print(f"{FULL_ACRONYM} ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
