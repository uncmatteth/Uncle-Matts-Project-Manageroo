from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .branding import FULL_ACRONYM, PROJECT_DIR, PUBLIC_COMMAND, print_banner
from .brief_builder import build_product_brief, default_brief_path, write_product_brief
from .checks import (
    add_check_gate,
    format_add_check_gate,
    format_check_gate_list,
    format_check_gate_suggestions,
    list_check_gates,
    suggest_check_gates,
)
from .chiptune import play_once
from .config import AGENT_PRESETS, apply_agent_preset
from .doctor import doctor
from .errors import UMSMFBURASBOFEError
from .gbrain_setup import format_gbrain_setup, gbrain_setup_status
from .ideas import IdeaInbox
from .install_status import (
    format_stack_status,
    format_uninstall_plan,
    stack_status,
    uninstall_plan,
)
from .install_repair import format_repair_install, repair_install
from .integration_config import configure_integrations, format_integration_config
from .loop_library import (
    DEFAULT_CATALOG_URL,
    find_loop,
    format_loop_list,
    load_catalog,
    loop_brief,
    loop_control_profile,
    loop_summary,
    search_loops,
    write_loop_brief,
)
from .orchestrator import Orchestrator
from .project import create_project_repo, git_root, initialize_project
from .readiness import brief_is_template, format_readiness, readiness
from .release_ready import format_release_ready, release_ready
from .selftest import run_self_test
from .skill_pack import (
    format_skill_import,
    format_skill_scan,
    import_skill_folder,
    scan_skill_folder,
)
from .solo import format_solo_report, solo_next_command
from .token_modes import (
    CORE_HELPER_SKILLS,
    install_core_helper_skills,
    install_token_skills,
    read_token_mode,
    set_token_mode,
)
from .util import read_json
from .wizards import collect_gbrain_answers, collect_setup_answers, collect_solo_answers


def _repo(value: str | None) -> Path:
    return git_root(Path(value or ".").resolve())


def _prompt_missing(value: str, prompt: str) -> str:
    if value.strip() or not sys.stdin.isatty():
        return value
    return input(prompt).strip()


def _integration_guidance(preferences: dict[str, bool], agent: str) -> list[dict]:
    items: list[dict] = []
    if preferences.get("gbrain"):
        report = gbrain_setup_status()
        source_count = report.get("status", {}).get("source_count", 0)
        gbrain_ready = bool(report.get("ok") and source_count > 0)
        next_command = (
            "umsmfburasbofe gbrain-setup --source-id my-project "
            "--path /absolute/path/to/repo --apply --sync"
        )
        if report.get("next_commands"):
            next_command = report["next_commands"][0]
        items.append(
            {
                "name": "gbrain",
                "ok": gbrain_ready,
                "detail": (
                    "mapped sources ready"
                    if gbrain_ready
                    else "needs install, health fix, MCP wiring, or source mapping"
                ),
                "next": (
                    "Connect `gbrain serve` to your selected agent."
                    if gbrain_ready
                    else next_command
                ),
            }
        )
    if preferences.get("gitnexus"):
        installed = shutil.which("gitnexus")
        items.append(
            {
                "name": "gitnexus",
                "ok": bool(installed),
                "detail": installed or "missing",
                "next": "gitnexus setup" if installed else "npm install -g gitnexus",
            }
        )
    if preferences.get("obsidian"):
        installed = shutil.which("obsidian")
        items.append(
            {
                "name": "obsidian",
                "ok": bool(installed),
                "detail": installed or "missing",
                "next": "Install Obsidian from https://obsidian.md/download",
            }
        )
    if preferences.get("loop_library"):
        npx = shutil.which("npx")
        candidates = [
            Path.home() / ".agents" / "skills" / "loop-library" / "SKILL.md",
            Path.home() / ".codex" / "skills" / "loop-library" / "SKILL.md",
        ]
        existing = next((path for path in candidates if path.is_file()), None)
        command = (
            "npx --yes skills add Forward-Future/loop-library "
            f"--skill loop-library --agent {agent} -g -y"
        )
        items.append(
            {
                "name": "loop-library",
                "ok": bool(existing),
                "detail": str(existing) if existing else "missing agent skill",
                "next": (
                    ""
                    if existing
                    else command
                    if npx
                    else "Install Node.js/npm, then rerun setup."
                ),
            }
        )
    return items


def _format_integration_guidance(items: list[dict]) -> str:
    if not items:
        return ""
    lines = ["Selected integrations:"]
    for item in items:
        label = "OK" if item.get("ok") else "ACTION"
        lines.append(f"{label} {item['name']}: {item['detail']}")
    return "\n".join(lines) + "\n"


def _setup_next_command(readiness_report: dict, integration_config: dict) -> str:
    for item in readiness_report.get("items", []):
        if item.get("required", True) and not item.get("ok") and item.get("next"):
            return item["next"]
    if not integration_config.get("ok") and integration_config.get("next_command"):
        return integration_config["next_command"]
    if readiness_report.get("ok"):
        return f"{PUBLIC_COMMAND} run --apply"
    commands = readiness_report.get("next_commands", [])
    return commands[0] if commands else f"{PUBLIC_COMMAND} ready"


def _extract_check_repo_arg(argv: list[str], repo: str) -> tuple[str, list[str]]:
    values = list(argv)
    command_start = values.index("--") if "--" in values else len(values)
    prefix = values[:command_start]
    suffix = values[command_start:]
    cleaned: list[str] = []
    index = 0
    selected_repo = repo
    while index < len(prefix):
        if prefix[index] == "--repo" and index + 1 < len(prefix):
            selected_repo = prefix[index + 1]
            index += 2
            continue
        cleaned.append(prefix[index])
        index += 1
    return selected_repo, cleaned + suffix


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog=PUBLIC_COMMAND,
        description=f"{FULL_ACRONYM} coding-agent control plane.",
    )
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help=f"Install project-local {FULL_ACRONYM} assets.")
    init.add_argument("repo", nargs="?", default=".")
    init.add_argument("--agent", choices=sorted(AGENT_PRESETS), default="codex")
    init.add_argument("--create", action="store_true", help="Create a missing or empty Git repository first.")

    setup = sub.add_parser("setup", help="Guided first-run setup for a product repository.")
    setup.add_argument("repo", nargs="?")
    setup.add_argument("--agent", choices=sorted(AGENT_PRESETS))
    setup.add_argument("--token-mode", choices=["off", "caveman", "curse"])
    setup.add_argument("--skip-skills", action="store_true")
    setup.add_argument("--json", action="store_true")

    solo = sub.add_parser(
        "solo",
        help="Solo-operator flow: project, ask, brief, readiness, and one next action.",
    )
    solo.add_argument("repo", nargs="?")
    solo.add_argument("--agent", choices=sorted(AGENT_PRESETS))
    solo.add_argument("--want", default="")
    solo.add_argument("--for", dest="audience", default="")
    solo.add_argument("--outcome", action="append", default=[])
    solo.add_argument("--must-not", action="append", default=[])
    solo.add_argument("--proof", action="append", default=[])
    solo.add_argument("--stop", default="")
    solo.add_argument("--later", action="append", default=[])
    solo.add_argument("--mode", choices=["build", "repair"], default="build")
    solo.add_argument("--token-mode", choices=["off", "caveman", "curse"])
    solo.add_argument("--skip-skills", action="store_true")
    solo.add_argument("--use-gbrain", action="store_true")
    solo.add_argument("--use-gitnexus", action="store_true")
    solo.add_argument("--use-obsidian", action="store_true")
    solo.add_argument("--use-loop-library", action="store_true")
    solo.add_argument("--run", action="store_true")
    solo.add_argument("--create", action="store_true", help="Create a missing or empty Git repository first.")
    solo.add_argument("--force", action="store_true")
    solo.add_argument("--json", action="store_true")
    solo_apply = solo.add_mutually_exclusive_group()
    solo_apply.add_argument("--apply", dest="apply", action="store_true", default=True)
    solo_apply.add_argument("--no-apply", dest="apply", action="store_false")

    ready = sub.add_parser("ready", help="Say exactly what is ready, missing, optional, and next.")
    ready.add_argument("repo", nargs="?", default=".")
    ready.add_argument("--require-gbrain", action="store_true")
    ready.add_argument("--json", action="store_true")

    release = sub.add_parser(
        "release-ready",
        help="Final operator gate before a manual production release.",
    )
    release.add_argument("repo", nargs="?", default=".")
    release.add_argument("--target", default="")
    release.add_argument("--rollback", default="")
    release.add_argument("--approved-by", default="")
    release.add_argument("--save", action="store_true", help="Save release metadata in the repo.")
    release.add_argument("--no-run-checks", action="store_true")
    release.add_argument("--json", action="store_true")

    checks = sub.add_parser("checks", help="List or add real verification commands.")
    checks_sub = checks.add_subparsers(dest="checks_command", required=True)
    checks_list = checks_sub.add_parser("list", help="List configured verification commands.")
    checks_list.add_argument("repo", nargs="?", default=".")
    checks_list.add_argument("--json", action="store_true")
    checks_suggest = checks_sub.add_parser("suggest", help="Suggest real check commands for this repo.")
    checks_suggest.add_argument("repo", nargs="?", default=".")
    checks_suggest.add_argument("--json", action="store_true")
    checks_add = checks_sub.add_parser(
        "add",
        help="Add one real check command. Run checks suggest first if unsure.",
    )
    checks_add.add_argument("id")
    checks_add.add_argument("argv", nargs=argparse.REMAINDER)
    checks_add.add_argument("--repo", default=".")
    checks_add.add_argument("--kind", default="check")
    checks_add.add_argument("--timeout-seconds", type=int, default=1800)
    checks_add.add_argument("--optional", action="store_true")
    checks_add.add_argument("--json", action="store_true")

    brief = sub.add_parser(
        "brief",
        help="Turn a plain request into .umsmfburasbofe/PRODUCT-BRIEF.md.",
    )
    brief.add_argument("repo", nargs="?", default=".")
    brief.add_argument("--want", default="")
    brief.add_argument("--for", dest="audience", default="")
    brief.add_argument("--outcome", action="append", default=[])
    brief.add_argument("--must-not", action="append", default=[])
    brief.add_argument("--proof", action="append", default=[])
    brief.add_argument("--stop", default="")
    brief.add_argument("--later", action="append", default=[])
    brief.add_argument("--output", type=Path)
    brief.add_argument("--force", action="store_true")
    brief.add_argument("--print", dest="print_brief", action="store_true")

    gbrain_setup = sub.add_parser(
        "gbrain-setup",
        help="Inspect and safely map selected folders into GBrain.",
    )
    gbrain_setup.add_argument("--source-id")
    gbrain_setup.add_argument("--path", type=Path)
    gbrain_setup.add_argument("--apply", action="store_true")
    gbrain_setup.add_argument("--sync", action="store_true")
    gbrain_setup.add_argument("--json", action="store_true")

    integrations = sub.add_parser("integrations", help="Configure optional GBrain/GitNexus command wiring.")
    integrations_sub = integrations.add_subparsers(dest="integrations_command", required=True)
    integrations_configure = integrations_sub.add_parser(
        "configure",
        help="Detect installed GBrain/GitNexus and write integration command templates.",
    )
    integrations_configure.add_argument("repo", nargs="?", default=".")
    integrations_configure.add_argument("--no-gbrain", action="store_true")
    integrations_configure.add_argument("--no-gitnexus", action="store_true")
    integrations_configure.add_argument("--no-apply", action="store_true")
    integrations_configure.add_argument("--force", action="store_true")
    integrations_configure.add_argument("--json", action="store_true")

    agent = sub.add_parser("agent", help="Inspect or switch agent CLI presets.")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_sub.add_parser("list", help="List built-in agent presets.")
    agent_preset_cmd = agent_sub.add_parser(
        "preset",
        help="Apply one agent preset to an initialized repo.",
    )
    agent_preset_cmd.add_argument("name", choices=sorted(AGENT_PRESETS))
    agent_preset_cmd.add_argument("repo", nargs="?", default=".")
    agent_preset_cmd.add_argument("--json", action="store_true")

    doc = sub.add_parser("doctor", help="Validate the local environment without modifying code.")
    doc.add_argument("repo", nargs="?", default=".")
    doc.add_argument("--json", action="store_true")

    run = sub.add_parser("run", help="Run the complete one-request workflow.")
    run.add_argument("--repo", default=".")
    run.add_argument("--brief")
    run.add_argument("--mode", choices=["build", "repair"], default="build")
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

    skills = sub.add_parser("skills", help="Install or list the recommended local agent skill pack.")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_sub.add_parser("install", help="Install the recommended local agent skill pack.")
    skills_sub.add_parser("list", help="List bundled skills in the recommended pack.")
    skills_scan = skills_sub.add_parser("scan", help="Scan a copied skills folder without changing anything.")
    skills_scan.add_argument("source", type=Path)
    skills_scan.add_argument("--skills-dir", type=Path)
    skills_scan.add_argument("--limit", type=int, default=80, help="Plain-text item limit. Use 0 for all.")
    skills_scan.add_argument("--json", action="store_true")
    skills_import = skills_sub.add_parser("import", help="Import SKILL.md files from a copied skills folder.")
    skills_import.add_argument("source", type=Path)
    skills_import.add_argument("--skills-dir", type=Path)
    skills_import.add_argument("--apply", action="store_true")
    skills_import.add_argument("--limit", type=int, default=80, help="Plain-text item limit for dry runs. Use 0 for all.")
    skills_import.add_argument("--json", action="store_true")

    stack = sub.add_parser("stack-status", help="Show installed/skipped/fix-next status for the guided local stack.")
    stack.add_argument("--lock", type=Path)
    stack.add_argument("--json", action="store_true")

    uninstall = sub.add_parser("uninstall-plan", help="Print the core uninstall plan without deleting anything.")
    uninstall.add_argument("--prefix", type=Path)
    uninstall.add_argument("--bin-dir", type=Path)
    uninstall.add_argument("--json", action="store_true")

    repair = sub.add_parser(
        "repair-install",
        help="Inspect and repair the local launcher/helper install.",
    )
    repair.add_argument("--prefix", type=Path)
    repair.add_argument("--bin-dir", type=Path)
    repair.add_argument("--no-apply", action="store_true")
    repair.add_argument("--json", action="store_true")

    loops = sub.add_parser("loop-library", help="Use Matthew Berman / Forward Future Loop Library loops.")
    loops.add_argument("--catalog-url", default=DEFAULT_CATALOG_URL)
    loops.add_argument("--catalog-file", type=Path)
    loops.add_argument("--cache-file", type=Path)
    loops.add_argument("--refresh", action="store_true", help="Fetch the live catalog instead of falling back to cache.")
    loops_sub = loops.add_subparsers(dest="loop_command", required=True)
    loop_search = loops_sub.add_parser("search", help="Search the live Loop Library catalog.")
    loop_search.add_argument("query", nargs="*", help="Search words. Omit to list the first loops.")
    loop_search.add_argument("--limit", type=int, default=10)
    loop_show = loops_sub.add_parser("show", help="Show one Loop Library loop as JSON.")
    loop_show.add_argument("loop")
    loop_profile = loops_sub.add_parser("profile", help="Show the controller profile for one loop.")
    loop_profile.add_argument("loop")
    loop_brief_cmd = loops_sub.add_parser("brief", help="Generate a product brief from a loop.")
    loop_brief_cmd.add_argument("loop")
    loop_brief_cmd.add_argument("--request", default="")
    loop_brief_cmd.add_argument("--output", type=Path)
    loop_brief_cmd.add_argument("--force", action="store_true")

    sub.add_parser("self-test", help="Run a deterministic mock end-to-end build.")

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            created_project = None
            if args.create:
                created_project = create_project_repo(Path(args.repo), title=Path(args.repo).name)
            result = initialize_project(Path(args.repo), agent=args.agent)
            if created_project:
                result["created_project"] = created_project
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "setup":
            answers = collect_setup_answers(
                repo=args.repo,
                agent=args.agent,
                interactive=sys.stdin.isatty() and not args.json,
            )
            result = initialize_project(Path(answers["repo"]), agent=answers["agent"])
            repo = Path(result["repo"])
            agent_result = apply_agent_preset(repo, answers["agent"])
            skills_result = [] if args.skip_skills else install_core_helper_skills()
            token_result = set_token_mode(args.token_mode) if args.token_mode else read_token_mode()
            integrations = _integration_guidance(answers["integrations"], answers["agent"])
            integration_config = configure_integrations(
                repo,
                gbrain=bool(answers["integrations"].get("gbrain")),
                gitnexus=bool(answers["integrations"].get("gitnexus")),
                apply=True,
            )
            ready_result = readiness(repo)
            next_command = _setup_next_command(ready_result, integration_config)
            payload = {
                "ok": True,
                "init": result,
                "agent": agent_result,
                "installed_skills": skills_result,
                "token_mode": token_result,
                "selected_integrations": integrations,
                "integration_config": integration_config,
                "readiness": ready_result,
                "next_command": next_command,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print("SETUP COMPLETE")
                print(f"Repo: {result['repo']}")
                print(f"Brief: {result['brief']}")
                print(f"Agent preset: {answers['agent']}")
                if integrations:
                    print("")
                    print(_format_integration_guidance(integrations), end="")
                print("")
                print(format_readiness(ready_result, include_next=False), end="")
                print("")
                print(f"Next: {next_command}")
            return 0

        if args.command == "solo":
            requested_integrations = {
                "gbrain": args.use_gbrain,
                "gitnexus": args.use_gitnexus,
                "obsidian": args.use_obsidian,
                "loop_library": args.use_loop_library,
            }
            answers = collect_solo_answers(
                repo=args.repo,
                agent=args.agent,
                want=args.want,
                audience=args.audience,
                outcomes=args.outcome,
                must_not=args.must_not,
                proof=args.proof,
                stop=args.stop,
                later=args.later,
                mode=args.mode,
                run=True if args.run else None,
                integrations=requested_integrations,
                interactive=sys.stdin.isatty() and not args.json,
            )
            created_project = None
            if args.create:
                created_project = create_project_repo(
                    Path(answers["repo"]),
                    title=Path(answers["repo"]).name,
                    description=answers["want"],
                )
            result = initialize_project(Path(answers["repo"]), agent=answers["agent"])
            repo = Path(result["repo"])
            agent_result = apply_agent_preset(repo, answers["agent"])
            skills_result = [] if args.skip_skills else install_core_helper_skills()
            token_result = set_token_mode(args.token_mode) if args.token_mode else read_token_mode()
            markdown = build_product_brief(
                want=answers["want"],
                audience=answers["audience"],
                outcomes=answers["outcomes"],
                must_not=answers["must_not"],
                proof=answers["proof"],
                stop_rule=answers["stop"],
                later=answers["later"],
            )
            brief_path = default_brief_path(repo)
            brief_force = args.force or brief_is_template(brief_path)
            written_brief = write_product_brief(brief_path, markdown, force=brief_force)
            integration_config = configure_integrations(
                repo,
                gbrain=bool(answers["integrations"].get("gbrain")),
                gitnexus=bool(answers["integrations"].get("gitnexus")),
                apply=True,
            )
            integration_guidance = _integration_guidance(answers["integrations"], answers["agent"])
            ready_result = readiness(repo)
            run_result = None
            run_skipped_reason = ""
            if answers["run"]:
                if ready_result["ok"]:
                    run_result = Orchestrator(repo).run(
                        brief_path=written_brief,
                        mode=answers["mode"],
                        apply_on_success=args.apply,
                    )
                else:
                    run_skipped_reason = "readiness is not passing yet"
            next_command = solo_next_command(
                ready_result,
                integration_config,
                integration_guidance=integration_guidance,
                mode=answers["mode"],
                apply_on_success=args.apply,
                run_result=run_result,
            )
            payload = {
                "ok": True,
                "flow": "solo-operator",
                "repo": str(repo),
                "brief": str(written_brief),
                "agent_name": answers["agent"],
                "agent": agent_result,
                "created_project": created_project,
                "mode": answers["mode"],
                "installed_skills": skills_result,
                "token_mode": token_result,
                "integration_config": integration_config,
                "integration_guidance": integration_guidance,
                "readiness": ready_result,
                "run": run_result,
                "run_skipped_reason": run_skipped_reason,
                "next_command": next_command,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print(format_solo_report(payload), end="")
            return 0

        if args.command == "ready":
            result = readiness(Path(args.repo).resolve(), require_gbrain=args.require_gbrain)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(format_readiness(result), end="")
            return 0 if result["ok"] else 2

        if args.command == "release-ready":
            result = release_ready(
                Path(args.repo).resolve(),
                target=args.target,
                rollback=args.rollback,
                approved_by=args.approved_by,
                run_checks=not args.no_run_checks,
                save=args.save,
            )
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(format_release_ready(result), end="")
            return 0 if result["ok"] else 2

        if args.command == "checks":
            if args.checks_command == "list":
                repo = _repo(args.repo)
                result = list_check_gates(repo)
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(format_check_gate_list(result), end="")
                return 0
            if args.checks_command == "suggest":
                repo = _repo(args.repo)
                result = suggest_check_gates(repo)
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(format_check_gate_suggestions(result), end="")
                return 0
            selected_repo, check_argv = _extract_check_repo_arg(args.argv, args.repo)
            repo = _repo(selected_repo)
            result = add_check_gate(
                repo,
                gate_id=args.id,
                argv=check_argv,
                kind=args.kind,
                timeout_seconds=args.timeout_seconds,
                required=not args.optional,
            )
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(format_add_check_gate(result), end="")
            return 0

        if args.command == "brief":
            repo = _repo(args.repo)
            want = _prompt_missing(args.want, "What do you want this repo to do/change? ")
            audience = _prompt_missing(args.audience, "Who is it for? ")
            markdown = build_product_brief(
                want=want,
                audience=audience,
                outcomes=args.outcome,
                must_not=args.must_not,
                proof=args.proof,
                stop_rule=args.stop,
                later=args.later,
            )
            output = args.output or default_brief_path(repo)
            if args.print_brief:
                print(markdown)
            else:
                path = write_product_brief(output, markdown, force=args.force)
                print(path)
            return 0

        if args.command == "gbrain-setup":
            answers = collect_gbrain_answers(
                source_id=args.source_id,
                source_path=args.path,
                apply=args.apply,
                sync=args.sync,
                interactive=sys.stdin.isatty() and not args.json,
            )
            result = gbrain_setup_status(
                source_id=answers["source_id"],
                source_path=answers["source_path"],
                apply=answers["apply"],
                sync=answers["sync"],
            )
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(format_gbrain_setup(result), end="")
            return 0 if result["ok"] else 2

        if args.command == "integrations":
            repo = _repo(args.repo)
            result = configure_integrations(
                repo,
                gbrain=not args.no_gbrain,
                gitnexus=not args.no_gitnexus,
                apply=not args.no_apply,
                force=args.force,
            )
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(format_integration_config(result), end="")
            return 0 if result["ok"] else 2

        if args.command == "agent":
            if args.agent_command == "list":
                print(json.dumps({"presets": sorted(AGENT_PRESETS)}, indent=2))
                return 0
            repo = _repo(args.repo)
            result = apply_agent_preset(repo, args.name)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"Applied agent preset `{args.name}` to {result['config']}")
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
            brief_path = (
                Path(args.brief).resolve()
                if args.brief
                else repo / PROJECT_DIR / "PRODUCT-BRIEF.md"
            )
            result = Orchestrator(repo).run(
                brief_path=brief_path,
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

        if args.command == "skills":
            if args.skills_command == "install":
                print(json.dumps({"installed_skills": install_core_helper_skills()}, indent=2))
            elif args.skills_command == "scan":
                result = scan_skill_folder(args.source, skills_dir=args.skills_dir)
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(format_skill_scan(result, limit=args.limit), end="")
                return 0
            elif args.skills_command == "import":
                result = import_skill_folder(
                    args.source,
                    skills_dir=args.skills_dir,
                    apply=args.apply,
                )
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(format_skill_import(result, limit=args.limit), end="")
                return 0
            else:
                print(json.dumps({"bundled_skills": sorted(CORE_HELPER_SKILLS)}, indent=2))
            return 0

        if args.command == "stack-status":
            result = stack_status(args.lock)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(format_stack_status(result), end="")
            return 0 if result.get("ok") else 2

        if args.command == "uninstall-plan":
            result = uninstall_plan(args.prefix, args.bin_dir)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(format_uninstall_plan(result), end="")
            return 0

        if args.command == "repair-install":
            result = repair_install(
                prefix=args.prefix,
                bin_dir=args.bin_dir,
                apply=not args.no_apply,
            )
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(format_repair_install(result), end="")
            return 0 if result["ok"] else 2

        if args.command == "loop-library":
            catalog = load_catalog(
                args.catalog_url,
                args.catalog_file,
                cache_file=args.cache_file,
                refresh=args.refresh,
            )
            if args.loop_command == "search":
                print(format_loop_list(search_loops(catalog, " ".join(args.query), limit=args.limit)), end="")
                return 0
            selected = find_loop(catalog, args.loop)
            if args.loop_command == "show":
                print(json.dumps(loop_summary(selected), indent=2))
                return 0
            if args.loop_command == "profile":
                print(json.dumps(loop_control_profile(selected), indent=2))
                return 0
            if args.output:
                path = write_loop_brief(args.output, selected, request=args.request, force=args.force)
                print(path)
            else:
                print(loop_brief(selected, request=args.request))
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
