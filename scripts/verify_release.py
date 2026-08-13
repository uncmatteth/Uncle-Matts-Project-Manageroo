#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from manageroo.truth_contract import find_overclaim_offenders  # noqa: E402

GENERATED = {"BUILD-VALIDATION.json", "SHA256SUMS.txt", "docs/FILE_MANIFEST.md"}
EXCLUDED_PARTS = {".git", ".venv", ".clawpatch", "__pycache__", "dist", "build"}
PUBLIC_TRUTH_FILES = (
    "README.md",
    "GITHUB_DESCRIPTION.md",
    "LOCAL_SETUP.md",
    "PUBLISH_TO_GITHUB.md",
    "GIVE-THIS-TO-YOUR-IDE-AGENT.md",
    "docs/00_START_HERE.md",
    "docs/INSTALLATION.md",
    "docs/LIMITATIONS.md",
    "docs/ARCHITECTURE.md",
    "docs/DOCUMENT_LANE.md",
    "docs/EXTERNAL_INTEGRATIONS.md",
    "docs/REVIEW_REPAIR_LANES.md",
    "docs/SOLO_OPERATOR_MODE.md",
    "docs/STATELESS_ORCHESTRATION.md",
)
BANNED_OVERCLAIM_PHRASES = (
    "full vision support",
    "real vision support",
    "understands screenshots",
    "understands images",
    "guaranteed production ready",
    "one-button production deploy",
    "autonomous production deploy",
    "real subagent swarm",
    "parallel implementation branches",
    "ai can fix autoreview findings",
    "ai can fix clawpatch findings",
    "silently self-improves",
)
UNIT_TEST_TIMEOUT_SECONDS = 900
PROCESS_TREE_GRACE_SECONDS = 5
RELEASE_FILE_LIST_ENV = "MANAGEROO_RELEASE_FILE_LIST"


def stable_command_output(output: str) -> str:
    return re.sub(r"Ran ([0-9]+) tests? in [0-9.]+s", r"Ran \1 tests in <elapsed>s", output)


def report_command_output(argv: list[str], exit_code: int, output: str) -> str:
    stable = stable_command_output(output)
    if exit_code != 0 or "unittest" not in argv:
        return stable
    summary = re.search(
        r"-{20,}\nRan [0-9]+ tests in <elapsed>s\n\nOK(?: \(skipped=[0-9]+\))?\n?\Z",
        stable,
    )
    return summary.group(0) if summary else stable


def _timeout_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _prefer_output(current: str, candidate: str | bytes | None) -> str:
    replacement = _timeout_output(candidate)
    return replacement if len(replacement) >= len(current) else current


def _taskkill_process_tree(process: subprocess.Popen[str], *, force: bool) -> bool:
    argv = ["taskkill", "/PID", str(process.pid), "/T"]
    if force:
        argv.append("/F")
    try:
        result = subprocess.run(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=PROCESS_TREE_GRACE_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _signal_process_tree(process: subprocess.Popen[str], *, force: bool) -> None:
    if os.name == "nt":
        signaled = _taskkill_process_tree(process, force=force)
        if not signaled and process.poll() is None:
            (process.kill if force else process.terminate)()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        if process.poll() is None:
            (process.kill if force else process.terminate)()


def run(
    argv: list[str],
    timeout: int = 300,
    *,
    env_overrides: dict[str, str] | None = None,
    env_remove: tuple[str, ...] = (),
) -> dict:
    env = os.environ.copy()
    for name in env_remove:
        env.pop(name, None)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env.update(env_overrides or {})
    popen_kwargs: dict = {
        "cwd": ROOT,
        "env": env,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "shell": False,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(argv, **popen_kwargs)
    try:
        output, _ = process.communicate(timeout=timeout)
        return {
            "argv": argv,
            "exit_code": process.returncode,
            "output": report_command_output(argv, process.returncode, output),
        }
    except subprocess.TimeoutExpired as exc:
        output = _timeout_output(exc.stdout)
        _signal_process_tree(process, force=False)
        cleanup_finished = False
        try:
            cleanup_output, _ = process.communicate(timeout=PROCESS_TREE_GRACE_SECONDS)
            output = _prefer_output(output, cleanup_output)
            cleanup_finished = True
        except subprocess.TimeoutExpired as cleanup_timeout:
            output = _prefer_output(output, cleanup_timeout.stdout)
        finally:
            _signal_process_tree(process, force=True)
        if not cleanup_finished:
            try:
                cleanup_output, _ = process.communicate(timeout=PROCESS_TREE_GRACE_SECONDS)
                output = _prefer_output(output, cleanup_output)
            except subprocess.TimeoutExpired as cleanup_timeout:
                output = _prefer_output(output, cleanup_timeout.stdout)
                process.kill()
                try:
                    process.wait(timeout=PROCESS_TREE_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                if process.stdout is not None:
                    process.stdout.close()
        return {"argv": argv, "exit_code": 124, "output": stable_command_output(output) + "\nTIMEOUT"}


@contextmanager
def snapshot_test_git_index():
    """Give nested package tests a local tracked-file view without trusting env input."""
    selector = os.environ.get(RELEASE_FILE_LIST_ENV)
    git_dir = ROOT / ".git"
    created = False
    if selector and not git_dir.exists() and not git_dir.is_symlink():
        subprocess.run(
            ["git", "init", "-q"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        created = True
        subprocess.run(
            ["git", "add", "-f", "--", "."],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
    try:
        yield
    finally:
        if created:
            if git_dir.is_symlink() or not git_dir.is_dir():
                raise RuntimeError("Temporary snapshot Git metadata changed during verification.")
            shutil.rmtree(git_dir)


def _relative(path: Path) -> Path:
    return path.relative_to(ROOT)


def _excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in _relative(path).parts)


def _package_release_module():
    module_path = ROOT / "scripts" / "package_release.py"
    if not module_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        "manageroo_package_release_for_verification",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load scripts/package_release.py for source selection.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_files() -> list[Path]:
    """Use the exact source-archive selector so validation and packaging bind the same tree."""
    module = _package_release_module()
    if module is None:
        # The end-user archive deliberately excludes the release publisher. Its
        # verifier must still be self-contained and able to validate that archive.
        return sorted(
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and not _excluded(path)
            and _relative(path).as_posix() not in GENERATED
        )
    return sorted(
        path
        for path in module.included_files()
        if _relative(path).as_posix() not in GENERATED
    )


def tree_hash() -> str:
    digest = hashlib.sha256()
    for path in source_files():
        digest.update(_relative(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def process_safety_violations() -> list[str]:
    violations: list[str] = []
    for path in source_files():
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    violations.append(f"shell=True:{_relative(path)}:{node.lineno}")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    violations.append(f"os.system:{_relative(path)}:{node.lineno}")
    return violations


def contains_compact(text: str, phrase: str) -> bool:
    return " ".join(phrase.split()).casefold() in " ".join(text.split()).casefold()


def public_truth_overclaim_violations() -> list[str]:
    violations: list[str] = []
    for relative in PUBLIC_TRUTH_FILES:
        path = ROOT / relative
        if not path.is_file():
            violations.append(f"missing-public-truth-file:{relative}")
            continue
        for phrase, sentence in find_overclaim_offenders(
            path.read_text(encoding="utf-8", errors="replace"),
            BANNED_OVERCLAIM_PHRASES,
        ):
            violations.append(f"{relative}:{phrase}:{sentence}")
    return violations


def structural_checks() -> list[dict]:
    required = [
        "install.sh", "install.ps1", "scripts/smoke_release_install.py", "scripts/finalize_gitnexus.py",
        "scripts/verify_distribution.py", "sitecustomize.py",
        "README.md", "GITHUB_DESCRIPTION.md", "LOCAL_SETUP.md", "PUBLISH_TO_GITHUB.md",
        "GIVE-THIS-TO-YOUR-IDE-AGENT.md", "docs/CONTEXT_COMPILER.md", "docs/DOCUMENT_LANE.md",
        "docs/EVIDENCE_RETRIEVAL.md", "docs/INSTALLATION.md", "docs/LEARNING_LANE.md", "docs/LIMITATIONS.md",
        "docs/REVIEW_REPAIR_LANES.md", "docs/SOLO_OPERATOR_MODE.md", "docs/STATELESS_ORCHESTRATION.md",
        "docs/TERMINAL_EXPERIENCE.md", "src/manageroo/branding.py", "src/manageroo/checks.py",
        "src/manageroo/chiptune.py", "src/manageroo/chiptune_policy.py", "src/manageroo/clawpatch_release.py",
        "src/manageroo/capability_router.py", "src/manageroo/document_lane.py",
        "src/manageroo/evidence.py", "src/manageroo/evidence_hardening.py", "src/manageroo/evidence_artifact_guard.py",
        "src/manageroo/evidence_policy.py", "src/manageroo/external_repair_policy.py", "src/manageroo/jobs.py",
        "src/manageroo/learning.py", "src/manageroo/next_action.py", "src/manageroo/project_memory.py",
        "src/manageroo/install_update.py", "src/manageroo/uninstall.py",
        "src/manageroo/release_proof_policy.py", "src/manageroo/release_ready_policy.py", "src/manageroo/skill_pack_policy.py",
        "src/manageroo/stack_update_policy.py", "src/manageroo/solo.py", "src/manageroo/token_modes.py",
        "src/manageroo/truth_contract.py", "src/manageroo/assets/skills/skill-vetter/SKILL.md",
        "src/manageroo/assets/skills/uncle-matts-project-manageroo/SKILL.md",
        "tests/test_acceptance_evidence.py", "tests/test_capability_router.py",
        "tests/test_clawpatch_release_sweep.py",
        "tests/test_clawpatch_remaining_regressions.py",
        "tests/test_evidence.py", "tests/test_evidence_policy.py", "tests/test_jobs.py", "tests/test_learning.py",
        "tests/test_release_hardening_contract.py", "tests/test_remaining_audit_regressions.py",
        "tests/test_codex_continuity_hooks.py",
        "tests/test_install_update.py", "tests/test_uninstall.py",
        "tests/test_transactional_adapter_hardening.py", "tests/test_transactional_history_and_pristine.py",
        "tests/test_truth_contract.py", "tests/test_truth_contract_production.py",
    ]
    checks = [{"name": f"required:{item}", "ok": (ROOT / item).is_file()} for item in required]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    limitations = (ROOT / "docs" / "LIMITATIONS.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    evidence = (ROOT / "docs" / "EVIDENCE_RETRIEVAL.md").read_text(encoding="utf-8")
    stateless = (ROOT / "docs" / "STATELESS_ORCHESTRATION.md").read_text(encoding="utf-8")
    review_repair = (ROOT / "docs" / "REVIEW_REPAIR_LANES.md").read_text(encoding="utf-8")
    skill = (ROOT / "src" / "manageroo" / "assets" / "skills" / "uncle-matts-project-manageroo" / "SKILL.md").read_text(encoding="utf-8")
    project = (ROOT / "src" / "manageroo" / "project.py").read_text(encoding="utf-8")
    selected = source_files()
    selected_relative = {_relative(path).as_posix() for path in selected}
    overclaims = public_truth_overclaim_violations()
    checks.extend([
        {"name": "release-source-not-empty", "ok": len(selected) > 20},
        {"name": "release-required-source-selected", "ok": {"README.md", "pyproject.toml", "src/manageroo/__init__.py"} <= selected_relative},
        {"name": "capability-router-source-selected", "ok": {"src/manageroo/capability_router.py", "tests/test_capability_router.py"} <= selected_relative},
        {"name": "complete-edition-name", "ok": "Project Manageroo" in readme},
        {"name": "no-old-brand", "ok": "".join(("bt", "tlabs.fun")) not in readme},
        {"name": "no-editor-specific-root", "ok": not (ROOT / ".vscode").exists()},
        {"name": "no-bundled-audio-assets", "ok": not any(path.suffix.lower() in {".wav", ".mp3", ".ogg", ".flac"} for path in selected)},
        {"name": "truth:production-overclaim-checker", "ok": not overclaims, "violations": overclaims},
        {
            "name": "truth:no-real-vision-claim",
            "ok": contains_compact(limitations, "it does not perform real vision interpretation or design understanding")
            and contains_compact(project, "pretend media metadata is real vision"),
        },
        {
            "name": "truth:no-fake-subagent-claim",
            "ok": contains_compact(architecture, "Tasks are dependency ordered and executed sequentially")
            and contains_compact(architecture, "Manageroo does not run parallel implementation branches against the same files"),
        },
        {
            "name": "truth:no-ai-freehand-external-repair",
            "ok": contains_compact(review_repair, "must not freehand fixes from AUTOREVIEW or Clawpatch findings")
            and contains_compact(skill, "Do not convert their findings into untracked AI freehand fixes"),
        },
        {
            "name": "truth:no-release-ready-deploy-claim",
            "ok": contains_compact(limitations, "`release-ready` is a final operator gate, not a deployment tool")
            and contains_compact(limitations, "It does not push, deploy, monitor, or roll back production."),
        },
        {
            "name": "truth:no-silent-self-mutation",
            "ok": contains_compact(limitations, "does not silently edit skills, docs, config, installer behavior, checks, prompts, or code"),
        },
        {
            "name": "truth:stateless-worker-orchestration",
            "ok": contains_compact(stateless, 'Manageroo is not "AI remembers better." Manageroo makes remembering unnecessary.'),
        },
        {
            "name": "truth:worker-scope-boundary",
            "ok": contains_compact(architecture, "The stronger repository boundary controls processes launched through `manageroo run`")
            and contains_compact(skill, "The current operator request owns the work")
            and contains_compact(limitations, "Manageroo installs Codex continuity hooks")
            and contains_compact(limitations, "Controlled runs remain the stronger isolated worker boundary"),
        },
        {
            "name": "truth:evidence-is-context-not-authority",
            "ok": contains_compact(evidence, "retrieved evidence is context")
            and contains_compact(evidence, "cannot certify one"),
        },
        {
            "name": "truth:gitnexus-gbrain-evidence-provider-boundary",
            "ok": contains_compact(evidence, "GitNexus remains the first-class repository/code-graph intelligence integration")
            and contains_compact(evidence, "GBrain remains the external durable knowledge lane")
            and contains_compact(evidence, "None of them can mark a run `COMPLETE`"),
        },
        {
            "name": "no-github-actions-workflows",
            "ok": not any(
                _relative(path).as_posix().startswith(".github/workflows/")
                for path in selected
            ),
        },
    ])
    return checks


def main(*, write_report: bool = True) -> int:
    with tempfile.TemporaryDirectory(prefix="manageroo-verify-bytecode-") as bytecode_cache:
        isolated_python_env = {"PYTHONPYCACHEPREFIX": bytecode_cache}
        commands = [
            run(
                [sys.executable, "-m", "compileall", "-q", "src"],
                env_overrides=isolated_python_env,
            )
        ]
        with snapshot_test_git_index():
            commands.append(run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                timeout=UNIT_TEST_TIMEOUT_SECONDS,
                env_overrides=isolated_python_env,
                env_remove=(RELEASE_FILE_LIST_ENV,),
            ))
    if shutil.which("sh"):
        commands.append(run(["sh", "-n", "install.sh", "scripts/install.sh"]))

    violations = process_safety_violations()
    structures = structural_checks()
    report = {
        "ok": all(item["exit_code"] == 0 for item in commands) and not violations and all(item["ok"] for item in structures),
        "commands": commands,
        "python_process_safety_violations": violations,
        "structural_checks": structures,
        "source_tree_sha256": tree_hash(),
        "source_selection": "scripts/package_release.py included_files minus generated outputs",
    }
    if write_report:
        (ROOT / "BUILD-VALIDATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if any(argument != "--check-only" for argument in arguments) or arguments.count("--check-only") > 1:
        raise SystemExit("usage: verify_release.py [--check-only]")
    raise SystemExit(main(write_report="--check-only" not in arguments))
