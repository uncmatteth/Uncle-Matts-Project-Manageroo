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
        return {
            "argv": argv,
            "exit_code": completed.returncode,
            "output": stable_command_output(completed.stdout),
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return {"argv": argv, "exit_code": 124, "output": output + "\nTIMEOUT"}


def source_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in {".git", ".venv", "__pycache__", "dist", "build"} for part in path.parts)
        and path.relative_to(ROOT).as_posix() not in GENERATED
    )


def tree_hash() -> str:
    digest = hashlib.sha256()
    for path in source_files():
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def process_safety_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in {".git", ".venv", "__pycache__", "dist", "build"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    violations.append(f"shell=True:{path.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    violations.append(f"os.system:{path.relative_to(ROOT)}:{node.lineno}")
    return violations


def contains_compact(text: str, phrase: str) -> bool:
    return " ".join(phrase.split()) in " ".join(text.split())


def structural_checks() -> list[dict]:
    required = [
        "install.sh",
        "install.ps1",
        "README.md",
        "GIVE-THIS-TO-YOUR-IDE-AGENT.md",
        "docs/CONTEXT_COMPILER.md",
        "docs/DOCUMENT_LANE.md",
        "docs/INSTALLATION.md",
        "docs/LEARNING_LANE.md",
        "docs/LIMITATIONS.md",
        "docs/REVIEW_REPAIR_LANES.md",
        "docs/SOLO_OPERATOR_MODE.md",
        "docs/TERMINAL_EXPERIENCE.md",
        "src/manageroo/branding.py",
        "src/manageroo/checks.py",
        "src/manageroo/chiptune.py",
        "src/manageroo/document_lane.py",
        "src/manageroo/learning.py",
        "src/manageroo/next_action.py",
        "src/manageroo/project_memory.py",
        "src/manageroo/solo.py",
        "src/manageroo/token_modes.py",
        "src/manageroo/assets/skills/article-enrichment/SKILL.md",
        "src/manageroo/assets/skills/autoreview/SKILL.md",
        "src/manageroo/assets/skills/book-mirror/SKILL.md",
        "src/manageroo/assets/skills/brain-ops/SKILL.md",
        "src/manageroo/assets/skills/brain-pdf/SKILL.md",
        "src/manageroo/assets/skills/citation-fixer/SKILL.md",
        "src/manageroo/assets/skills/diagnose/SKILL.md",
        "src/manageroo/assets/skills/exact-text-replacement/SKILL.md",
        "src/manageroo/assets/skills/fix-my-bad-website/SKILL.md",
        "src/manageroo/assets/skills/idea-ingest/SKILL.md",
        "src/manageroo/assets/skills/ingest/SKILL.md",
        "src/manageroo/assets/skills/media-ingest/SKILL.md",
        "src/manageroo/assets/skills/pdf/SKILL.md",
        "src/manageroo/assets/skills/pimp-my-prompt/SKILL.md",
        "src/manageroo/assets/skills/plain-web-copy/SKILL.md",
        "src/manageroo/assets/skills/query/SKILL.md",
        "src/manageroo/assets/skills/reports/SKILL.md",
        "src/manageroo/assets/skills/strategic-reading/SKILL.md",
        "src/manageroo/assets/skills/write-a-skill/SKILL.md",
        "src/manageroo/assets/skills/edit-skill/SKILL.md",
        "src/manageroo/assets/skills/skillify/SKILL.md",
        "src/manageroo/assets/skills/tdd/SKILL.md",
        "src/manageroo/assets/skills/caveman/SKILL.md",
        "src/manageroo/assets/skills/uncle-matts-caveman-curse/SKILL.md",
        "src/manageroo/assets/skills/voice-note-ingest/SKILL.md",
        "tests/test_cli_next.py",
        "tests/test_document_lane.py",
        "tests/test_cli_memory.py",
        "tests/test_learning.py",
        "tests/test_truth_contract.py",
    ]
    checks = [{"name": f"required:{item}", "ok": (ROOT / item).is_file()} for item in required]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    limitations = (ROOT / "docs" / "LIMITATIONS.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    review_repair = (ROOT / "docs" / "REVIEW_REPAIR_LANES.md").read_text(encoding="utf-8")
    installer = (ROOT / "scripts" / "install.py").read_text(encoding="utf-8")
    project = (ROOT / "src" / "manageroo" / "project.py").read_text(encoding="utf-8")
    checks.extend(
        [
            {
                "name": "complete-edition-name",
                "ok": "Project Manageroo" in readme,
            },
            {"name": "no-old-brand", "ok": "".join(("bt", "tlabs.fun")) not in readme},
            {"name": "no-editor-specific-root", "ok": not (ROOT / ".vscode").exists()},
            {
                "name": "no-bundled-audio-assets",
                "ok": not any(
                    path.suffix.lower() in {".wav", ".mp3", ".ogg", ".flac"}
                    for path in source_files()
                ),
            },
            {
                "name": "truth:no-real-vision-claim",
                "ok": (
                    contains_compact(
                        limitations,
                        "it does not perform real vision interpretation or design understanding",
                    )
                    and contains_compact(project, "pretend media metadata is real vision")
                ),
            },
            {
                "name": "truth:no-fake-subagent-claim",
                "ok": (
                    contains_compact(
                        architecture,
                        "implementation prioritizes correctness over theatrical agent count",
                    )
                    and contains_compact(
                        architecture,
                        "The controller does not run parallel implementation branches",
                    )
                ),
            },
            {
                "name": "truth:no-ai-freehand-external-repair",
                "ok": (
                    contains_compact(review_repair, "must not freehand fixes from AUTOREVIEW or")
                    and contains_compact(installer, "AI must not freehand fixes from them")
                ),
            },
            {
                "name": "truth:no-release-ready-deploy-claim",
                "ok": (
                    contains_compact(
                        limitations,
                        "`release-ready` is a final operator gate, not a deployment tool",
                    )
                    and contains_compact(
                        limitations,
                        "It does not push, deploy, monitor, or roll back production.",
                    )
                ),
            },
            {
                "name": "truth:no-silent-self-mutation",
                "ok": contains_compact(
                    limitations,
                    "does not silently edit skills, docs, config, installer behavior, checks, prompts, or code",
                ),
            },
            {
                "name": "no-github-actions-workflows",
                "ok": not any(
                    path.relative_to(ROOT).as_posix().startswith(".github/workflows/")
                    for path in source_files()
                ),
            },
        ]
    )
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
        "ok": (
            all(item["exit_code"] == 0 for item in commands)
            and not violations
            and all(item["ok"] for item in structures)
        ),
        "commands": commands,
        "python_process_safety_violations": violations,
        "structural_checks": structures,
        "source_tree_sha256": tree_hash(),
    }
    (ROOT / "BUILD-VALIDATION.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
