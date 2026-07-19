from __future__ import annotations

from pathlib import Path
from typing import Any

from .token_modes import BUNDLED_SKILL_LIBRARY, CORE_SKILL_PACK, OPTIONAL_SKILL_PACK


def default_host_skill_roots() -> list[Path]:
    return [
        Path.home() / ".agents" / "skills",
        Path.home() / ".codex" / "skills",
    ]


def _skill_names(root: Path) -> set[str]:
    if not root.is_dir() or root.is_symlink():
        return set()
    return {
        path.parent.name
        for path in root.glob("*/SKILL.md")
        if path.is_file() and not path.is_symlink()
    }


def inspect_host_skills(roots: list[Path] | None = None) -> dict[str, Any]:
    selected_roots = [path.expanduser().resolve() for path in (roots or default_host_skill_roots())]
    locations: dict[str, list[str]] = {}
    for root in selected_roots:
        for name in sorted(_skill_names(root)):
            locations.setdefault(name, []).append(str(root / name / "SKILL.md"))

    installed = set(locations)
    core = sorted(installed & set(CORE_SKILL_PACK))
    optional_known = sorted(installed & set(OPTIONAL_SKILL_PACK))
    host_owned = sorted(installed - set(BUNDLED_SKILL_LIBRARY))
    missing_core = sorted(set(CORE_SKILL_PACK) - installed)

    return {
        "ok": True,
        "roots": [str(root) for root in selected_roots],
        "installed_count": len(installed),
        "manageroo_core_present": core,
        "manageroo_core_missing": missing_core,
        "known_optional_present": optional_known,
        "host_owned_or_external": host_owned,
        "locations": locations,
        "policy": {
            "manageroo_owns": "Only the portable core skills it explicitly installs.",
            "manageroo_may_use": (
                "Any relevant installed skill exposed by the host environment, subject to the task and safety rules."
            ),
            "manageroo_never_does_implicitly": (
                "Copy, delete, upgrade, or claim ownership of host-specific skills merely because they are installed."
            ),
        },
    }


def format_host_skills(report: dict[str, Any]) -> str:
    lines = [
        "HOST SKILL ENVIRONMENT",
        f"Installed skills found: {report['installed_count']}",
        f"Manageroo core present: {len(report['manageroo_core_present'])}",
        f"Manageroo core missing: {len(report['manageroo_core_missing'])}",
        f"Known optional skills present: {len(report['known_optional_present'])}",
        f"Host-owned/external skills: {len(report['host_owned_or_external'])}",
        "",
        "Boundary: Manageroo installs and owns only its portable core. Other installed skills belong to the host environment.",
    ]
    if report["manageroo_core_missing"]:
        lines.append("Missing core: " + ", ".join(report["manageroo_core_missing"]))
    if report["host_owned_or_external"]:
        lines.append("Host-owned/external: " + ", ".join(report["host_owned_or_external"]))
    return "\n".join(lines) + "\n"
