from __future__ import annotations

import json
import sys
from pathlib import Path

from .errors import ConfigurationError


def _node_manager(repo: Path) -> str | None:
    markers = {
        "pnpm": repo / "pnpm-lock.yaml",
        "yarn": repo / "yarn.lock",
        "npm": repo / "package-lock.json",
        "bun": repo / "bun.lock",
    }
    present = [name for name, path in markers.items() if path.exists()]
    if len(present) > 1:
        raise ConfigurationError(
            "Multiple JavaScript lockfiles found. Remove stale lockfiles before MANAGEROO initialization: "
            + ", ".join(present)
        )
    return present[0] if present else ("npm" if (repo / "package.json").exists() else None)


def detect_gates(repo: Path) -> list[dict]:
    gates: list[dict] = []

    if (repo / "package.json").exists():
        manager = _node_manager(repo) or "npm"
        package = json.loads((repo / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        ordered = [
            ("format-check", "format:check", "format"),
            ("lint", "lint", "lint"),
            ("typecheck", "typecheck", "typecheck"),
            ("test", "test", "test"),
            ("build", "build", "build"),
        ]
        for gate_id, script, kind in ordered:
            if script in scripts:
                argv = [manager, "run", script] if manager != "yarn" else ["yarn", script]
                gates.append({"id": gate_id, "kind": kind, "argv": argv, "required": True})

    pyproject_text = ""
    if (repo / "pyproject.toml").exists():
        pyproject_text = (repo / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
    if "[tool.ruff" in pyproject_text:
        gates.append({"id": "ruff", "kind": "lint", "argv": [sys.executable, "-m", "ruff", "check", "."], "required": True})
    if "[tool.pyright" in pyproject_text or (repo / "pyrightconfig.json").is_file():
        gates.append({"id": "pyright", "kind": "typecheck", "argv": [sys.executable, "-m", "pyright"], "required": True})
    if "pytest" in pyproject_text or (repo / "pytest.ini").exists():
        gates.append({"id": "pytest", "kind": "test", "argv": [sys.executable, "-m", "pytest"], "required": True})
    elif any(repo.glob("test*.py")) or (repo / "tests").exists():
        gates.append({"id": "unittest", "kind": "test", "argv": [sys.executable, "-m", "unittest", "discover"], "required": True})

    if (repo / "Cargo.toml").exists():
        gates.extend([
            {"id": "cargo-fmt", "kind": "format", "argv": ["cargo", "fmt", "--check"], "required": True},
            {"id": "cargo-test", "kind": "test", "argv": ["cargo", "test"], "required": True},
        ])

    if (repo / "go.mod").exists():
        gates.append({"id": "go-test", "kind": "test", "argv": ["go", "test", "./..."], "required": True})

    if (repo / "pom.xml").exists():
        gates.append({"id": "maven-test", "kind": "test", "argv": ["mvn", "test"], "required": True})

    if (repo / "gradlew").exists():
        gates.append({"id": "gradle-test", "kind": "test", "argv": ["./gradlew", "test"], "required": True})

    deduped: dict[str, dict] = {}
    for gate in gates:
        deduped[gate["id"]] = gate
    return list(deduped.values())
