from __future__ import annotations

from pathlib import Path
from typing import Any

from .token_modes import BUNDLED_SKILL_LIBRARY, CORE_SKILL_PACK, OPTIONAL_SKILL_PACK


HOST_CAPABILITY_GROUPS: dict[str, set[str]] = {
    "orchestration": {
        "agent-skills-integration",
        "codex-parent-session-orchestrator",
        "codex-subagent-orchestrator",
        "decision-mapping",
        "handoff",
        "plan-mode-default",
        "request-refactor-plan",
        "to-issues",
        "to-prd",
    },
    "engineering-quality": {
        "autoreview",
        "caveman-commit",
        "caveman-review",
        "codebase-design",
        "diagnosing-bugs",
        "domain-modeling",
        "implement",
        "improve-codebase-architecture",
        "qa",
        "review",
        "setup-pre-commit",
        "tdd",
        "triage",
    },
    "gitnexus": {
        "gitnexus-cli",
        "gitnexus-debugging",
        "gitnexus-exploring",
        "gitnexus-guide",
        "gitnexus-impact-analysis",
        "gitnexus-pr-review",
        "gitnexus-refactoring",
    },
    "retrieval-and-memory": {
        "chronicle",
        "memory",
        "obsidian",
        "obsidian-vault",
        "retrieval-reflex",
    },
    "web-and-ui": {
        "design-an-interface",
        "develop-web-game",
        "playwright",
        "playwright-interactive",
        "prototype",
        "scaffold-exercises",
        "vercel-composition-patterns",
        "vercel-react-best-practices",
        "vercel-react-native-skills",
        "web-design-guidelines",
    },
    "cloudflare": {
        "agents-sdk",
        "cloudflare",
        "cloudflare-email-service",
        "cloudflare-one",
        "cloudflare-one-migrations",
        "durable-objects",
        "sandbox-sdk",
        "turnstile-spin",
        "web-perf",
        "workers-best-practices",
        "wrangler",
    },
    "writing-and-domain": {
        "edit-article",
        "plain-web-copy",
        "ubiquitous-language",
        "writing-beats",
        "writing-fragments",
        "writing-great-skills",
        "writing-shape",
    },
}


def default_host_skill_roots() -> list[Path]:
    return [
        Path.home() / ".agents" / "skills",
        Path.home() / ".codex" / "skills",
    ]


def _skill_files(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    root = root.resolve()
    found: list[Path] = []
    for path in root.rglob("SKILL.md"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError:
            continue
        found.append(path)
    return sorted(found)


def _skill_name(path: Path) -> str:
    return path.parent.name


def _capability_groups(installed: set[str]) -> dict[str, list[str]]:
    return {
        group: sorted(installed & names)
        for group, names in HOST_CAPABILITY_GROUPS.items()
        if installed & names
    }


def inspect_host_skills(roots: list[Path] | None = None) -> dict[str, Any]:
    selected_roots = [path.expanduser().resolve() for path in (roots or default_host_skill_roots())]
    locations: dict[str, list[str]] = {}
    for root in selected_roots:
        for skill_file in _skill_files(root):
            name = _skill_name(skill_file)
            locations.setdefault(name, []).append(str(skill_file))

    installed = set(locations)
    core = sorted(installed & set(CORE_SKILL_PACK))
    optional_known = sorted(installed & set(OPTIONAL_SKILL_PACK))
    host_owned = sorted(installed - set(BUNDLED_SKILL_LIBRARY))
    missing_core = sorted(set(CORE_SKILL_PACK) - installed)
    duplicates = {
        name: paths
        for name, paths in sorted(locations.items())
        if len(paths) > 1
    }

    return {
        "ok": True,
        "roots": [str(root) for root in selected_roots],
        "installed_count": len(installed),
        "manageroo_core_present": core,
        "manageroo_core_missing": missing_core,
        "known_optional_present": optional_known,
        "host_owned_or_external": host_owned,
        "capability_groups": _capability_groups(installed),
        "duplicate_skill_locations": duplicates,
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
        f"Duplicate skill names: {len(report.get('duplicate_skill_locations', {}))}",
        "",
        "Boundary: Manageroo installs and owns only its portable core. Other installed skills belong to the host environment.",
    ]
    if report["manageroo_core_missing"]:
        lines.append("Missing core: " + ", ".join(report["manageroo_core_missing"]))
    groups = report.get("capability_groups", {})
    if groups:
        lines.append("")
        lines.append("Detected host capabilities:")
        for group, names in groups.items():
            lines.append(f"- {group}: " + ", ".join(names))
    if report["host_owned_or_external"]:
        lines.append("")
        lines.append("Host-owned/external: " + ", ".join(report["host_owned_or_external"]))
    if report.get("duplicate_skill_locations"):
        lines.append("")
        lines.append("Duplicate skill names found in multiple locations; keep host ownership explicit.")
    return "\n".join(lines) + "\n"
