#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = {"BUILD-VALIDATION.json", "SHA256SUMS.txt", "docs/FILE_MANIFEST.md"}


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
        return {"argv": argv, "exit_code": completed.returncode, "output": completed.stdout}
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
        "docs/REVIEW_REPAIR_LANES.md",
        "docs/SOLO_OPERATOR_MODE.md",
        "docs/TERMINAL_EXPERIENCE.md",
        "src/umsmfburasbofe/branding.py",
        "src/umsmfburasbofe/checks.py",
        "src/umsmfburasbofe/chiptune.py",
        "src/umsmfburasbofe/document_lane.py",
        "src/umsmfburasbofe/learning.py",
        "src/umsmfburasbofe/next_action.py",
        "src/umsmfburasbofe/project_memory.py",
        "src/umsmfburasbofe/solo.py",
        "src/umsmfburasbofe/token_modes.py",
        "src/umsmfburasbofe/assets/skills/article-enrichment/SKILL.md",
        "src/umsmfburasbofe/assets/skills/autoreview/SKILL.md",
        "src/umsmfburasbofe/assets/skills/book-mirror/SKILL.md",
        "src/umsmfburasbofe/assets/skills/brain-ops/SKILL.md",
        "src/umsmfburasbofe/assets/skills/brain-pdf/SKILL.md",
        "src/umsmfburasbofe/assets/skills/citation-fixer/SKILL.md",
        "src/umsmfburasbofe/assets/skills/diagnose/SKILL.md",
        "src/umsmfburasbofe/assets/skills/exact-text-replacement/SKILL.md",
        "src/umsmfburasbofe/assets/skills/fix-my-bad-website/SKILL.md",
        "src/umsmfburasbofe/assets/skills/idea-ingest/SKILL.md",
        "src/umsmfburasbofe/assets/skills/ingest/SKILL.md",
        "src/umsmfburasbofe/assets/skills/media-ingest/SKILL.md",
        "src/umsmfburasbofe/assets/skills/pdf/SKILL.md",
        "src/umsmfburasbofe/assets/skills/pimp-my-prompt/SKILL.md",
        "src/umsmfburasbofe/assets/skills/plain-web-copy/SKILL.md",
        "src/umsmfburasbofe/assets/skills/query/SKILL.md",
        "src/umsmfburasbofe/assets/skills/reports/SKILL.md",
        "src/umsmfburasbofe/assets/skills/strategic-reading/SKILL.md",
        "src/umsmfburasbofe/assets/skills/write-a-skill/SKILL.md",
        "src/umsmfburasbofe/assets/skills/edit-skill/SKILL.md",
        "src/umsmfburasbofe/assets/skills/skillify/SKILL.md",
        "src/umsmfburasbofe/assets/skills/tdd/SKILL.md",
        "src/umsmfburasbofe/assets/skills/caveman/SKILL.md",
        "src/umsmfburasbofe/assets/skills/uncle-matts-caveman-curse/SKILL.md",
        "src/umsmfburasbofe/assets/skills/voice-note-ingest/SKILL.md",
        "tests/test_cli_next.py",
        "tests/test_document_lane.py",
        "tests/test_cli_memory.py",
        "tests/test_learning.py",
    ]
    checks = [{"name": f"required:{item}", "ok": (ROOT / item).is_file()} for item in required]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checks.extend(
        [
            {
                "name": "complete-edition-name",
                "ok": "Ultimate Remix All-Star Booty of Fire Edition" in readme,
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
