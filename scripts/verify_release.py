#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = {"BUILD-VALIDATION.json", "SHA256SUMS.txt", "docs/FILE_MANIFEST.md"}
EXCLUDED_PARTS = {".git", ".venv", ".clawpatch", "__pycache__", "dist", "build"}


def stable_command_output(output: str) -> str:
    return re.sub(r"Ran ([0-9]+) tests? in [0-9.]+s", r"Ran \1 tests in <elapsed>s", output)


def run(argv: list[str], timeout: int = 300) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            timeout=timeout,
        )
        return {"argv": argv, "exit_code": completed.returncode, "output": stable_command_output(completed.stdout)}
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return {"argv": argv, "exit_code": 124, "output": output + "\nTIMEOUT"}


def _relative(path: Path) -> Path:
    return path.relative_to(ROOT)


def _excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in _relative(path).parts)


def source_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not _excluded(path)
        and _relative(path).as_posix() not in GENERATED
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
    for path in sorted(ROOT.rglob("*.py")):
        if _excluded(path) or path.is_symlink():
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
    return " ".join(phrase.split()) in " ".join(text.split())


def structural_checks() -> list[dict]:
    required = [
        "install.sh", "install.ps1", "scripts/smoke_release_install.py", "scripts/finalize_gitnexus.py",
        "README.md", "GIVE-THIS-TO-YOUR-IDE-AGENT.md", "docs/CONTEXT_COMPILER.md", "docs/DOCUMENT_LANE.md",
        "docs/EVIDENCE_RETRIEVAL.md", "docs/INSTALLATION.md", "docs/LEARNING_LANE.md", "docs/LIMITATIONS.md",
        "docs/REVIEW_REPAIR_LANES.md", "docs/SOLO_OPERATOR_MODE.md", "docs/STATELESS_ORCHESTRATION.md",
        "docs/TERMINAL_EXPERIENCE.md", "src/manageroo/branding.py", "src/manageroo/checks.py",
        "src/manageroo/chiptune.py", "src/manageroo/document_lane.py", "src/manageroo/evidence.py",
        "src/manageroo/evidence_policy.py", "src/manageroo/jobs.py", "src/manageroo/learning.py",
        "src/manageroo/next_action.py", "src/manageroo/project_memory.py", "src/manageroo/solo.py",
        "src/manageroo/token_modes.py", "src/manageroo/assets/skills/skill-vetter/SKILL.md",
        "src/manageroo/assets/skills/uncle-matts-project-manageroo/SKILL.md", "tests/test_evidence.py",
        "tests/test_evidence_policy.py", "tests/test_jobs.py", "tests/test_learning.py", "tests/test_truth_contract.py",
        "tests/test_release_hardening_contract.py",
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
    checks.extend([
        {"name": "release-source-not-empty", "ok": len(selected) > 20},
        {"name": "release-required-source-selected", "ok": {"README.md", "pyproject.toml", "src/manageroo/__init__.py"} <= selected_relative},
        {"name": "complete-edition-name", "ok": "Project Manageroo" in readme},
        {"name": "no-old-brand", "ok": "".join(("bt", "tlabs.fun")) not in readme},
        {"name": "no-editor-specific-root", "ok": not (ROOT / ".vscode").exists()},
        {"name": "no-bundled-audio-assets", "ok": not any(path.suffix.lower() in {".wav", ".mp3", ".ogg", ".flac"} for path in selected)},
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
            "ok": not any(_relative(path).as_posix().startswith(".github/workflows/") for path in selected),
        },
    ])
    return checks


def main() -> int:
    commands = [
        run([sys.executable, "-m", "compileall", "-q", "src"]),
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]),
    ]
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
    }
    (ROOT / "BUILD-VALIDATION.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
