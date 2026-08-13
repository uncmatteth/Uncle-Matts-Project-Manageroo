from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .agent_continuity import (
    codex_continuity_hooks_status,
    continuity_state_root,
    remove_codex_continuity_hooks,
)
from .install_status import (
    DEFAULT_BIN_DIR,
    default_prefix,
    launcher_is_manageroo_owned,
    read_install_lock,
    uninstall_plan,
)
from .token_modes import (
    manageroo_owned_skill_inventory,
    remove_manageroo_owned_skills,
    token_mode_skills_dir,
    token_mode_state_path,
)


COMPONENT_IDS = ("runtime", "hooks", "skills", "state")


def _existing_paths(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths if path.exists() or path.is_symlink()]


def build_uninstall_inventory(
    *,
    prefix: Path | None = None,
    bin_dir: Path | None = None,
    codex_home: Path | None = None,
    skills_dir: Path | None = None,
    ownership_path: Path | None = None,
) -> dict[str, Any]:
    selected_prefix = (prefix or default_prefix()).expanduser()
    selected_bin = (bin_dir or DEFAULT_BIN_DIR).expanduser()
    plan = uninstall_plan(selected_prefix, selected_bin)
    loaded = read_install_lock(selected_prefix / "install-lock.json")
    lock = loaded.get("lock", {}) if loaded.get("ok") else {}
    launcher_value = lock.get("launcher")
    launcher = (
        Path(launcher_value).expanduser()
        if isinstance(launcher_value, str) and launcher_value
        else selected_bin / ("manageroo.cmd" if os.name == "nt" else "manageroo")
    )
    selected_codex_home = (
        codex_home
        or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    ).expanduser()
    hook_status = codex_continuity_hooks_status(
        codex_home=selected_codex_home,
        manageroo_command=launcher,
    )
    selected_skills = (skills_dir or token_mode_skills_dir()).expanduser()
    skill_inventory = manageroo_owned_skill_inventory(
        skills_dir=selected_skills,
        ownership_path=ownership_path,
    )
    state_paths = _existing_paths(
        [
            continuity_state_root().expanduser(),
            token_mode_state_path().expanduser(),
        ]
    )
    components = [
        {
            "id": "runtime",
            "label": "Manageroo runtime and launcher",
            "removable": bool(plan.get("prefix_ownership_known")),
            "paths": list(plan.get("core_paths") or []),
            "detail": plan.get("prefix_error") or "Ownership verified.",
        },
        {
            "id": "hooks",
            "label": "Codex always-on continuity hooks",
            "removable": bool(hook_status.get("ok")),
            "paths": [hook_status["hooks_path"]] if hook_status.get("ok") else [],
            "detail": hook_status.get("error") or "Installed for this Manageroo launcher.",
        },
        {
            "id": "skills",
            "label": "Unchanged Manageroo-owned portable skills",
            "removable": bool(skill_inventory["owned"]),
            "paths": list(skill_inventory["owned"]),
            "preserved_paths": list(skill_inventory["preserved"]),
            "detail": (
                f"{len(skill_inventory['owned'])} removable; "
                f"{len(skill_inventory['preserved'])} user-edited or unverified preserved."
            ),
        },
        {
            "id": "state",
            "label": "Manageroo continuity and preference state",
            "removable": bool(state_paths),
            "paths": state_paths,
            "detail": f"{len(state_paths)} Manageroo state path(s).",
        },
    ]
    surrounding_tools = []
    for item in lock.get("external_tools", []) if isinstance(lock, dict) else []:
        if not isinstance(item, dict):
            continue
        surrounding_tools.append(
            {
                "name": str(item.get("name") or "unknown"),
                "path": item.get("path"),
                "installed": bool(item.get("installed") or item.get("path")),
                "manageroo_owned": bool(item.get("manageroo_owned")),
                "automatic_removal": bool(
                    item.get("manageroo_owned")
                    and item.get("path") in plan.get("manageroo_owned_external_paths", [])
                ),
                "note": (
                    "Included with the runtime removal because exact ownership is proven."
                    if item.get("path") in plan.get("manageroo_owned_external_paths", [])
                    else "Shared or ownership-unproven tool; preserved automatically."
                ),
            }
        )
    return {
        "ok": bool(plan.get("prefix_ownership_known")),
        "prefix": str(selected_prefix),
        "launcher": str(launcher),
        "codex_home": str(selected_codex_home),
        "skills_dir": str(selected_skills),
        "ownership_path": skill_inventory["ownership_path"],
        "components": components,
        "by_id": {item["id"]: item for item in components},
        "surrounding_tools": surrounding_tools,
        "requires_confirmation": True,
        "applied": False,
    }


def _safe_state_target(path: Path) -> Path:
    lexical = path.expanduser().absolute()
    try:
        resolved = lexical.resolve(strict=False)
        dangerous = {
            Path(resolved.anchor).resolve(strict=False),
            Path.home().resolve(strict=False),
            Path.cwd().resolve(strict=False),
        }
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"Manageroo state path could not be resolved safely: {path}: {exc}") from exc
    if any(item == resolved or item.is_relative_to(resolved) for item in dangerous):
        raise ValueError(f"Refusing broad Manageroo state removal target: {resolved}")
    return lexical


def _remove_state_path(path: Path) -> None:
    target = _safe_state_target(path)
    if target.is_symlink():
        raise ValueError(f"Refusing to remove linked Manageroo state path: {target}")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def _remove_owned_runtime(prefix: Path, bin_dir: Path) -> list[str]:
    plan = uninstall_plan(prefix, bin_dir)
    if not plan.get("prefix_ownership_known"):
        raise ValueError(f"Manageroo runtime ownership is not verified: {plan.get('prefix_error')}")
    resolved_prefix = prefix.expanduser().resolve(strict=True)
    prefix_state = resolved_prefix.lstat()
    file_entries: list[tuple[Path, os.stat_result]] = []
    for raw_path in plan.get("core_paths", [])[1:]:
        path = Path(raw_path)
        if not path.exists() or path.is_symlink():
            continue
        if path.name in {"manageroo", "manageroo.cmd"} and not launcher_is_manageroo_owned(
            path,
            expected_prefix=resolved_prefix,
        ):
            raise ValueError(f"Manageroo launcher ownership changed during uninstall: {path}")
        if not path.is_file():
            raise ValueError(f"Refusing non-file Manageroo uninstall target: {path}")
        file_entries.append((path, path.lstat()))
    quarantine = resolved_prefix.with_name(
        f".{resolved_prefix.name}.manageroo-uninstall-{os.urandom(6).hex()}"
    )
    resolved_prefix.rename(quarantine)
    moved_state = quarantine.lstat()
    if (prefix_state.st_dev, prefix_state.st_ino) != (moved_state.st_dev, moved_state.st_ino):
        if not resolved_prefix.exists() and quarantine.exists():
            quarantine.rename(resolved_prefix)
        raise RuntimeError("Manageroo runtime changed during uninstall.")
    staged_files: list[tuple[Path, Path]] = []
    try:
        for path, state in file_entries:
            staged = path.with_name(
                f".{path.name}.manageroo-uninstall-{os.urandom(6).hex()}"
            )
            path.rename(staged)
            staged_state = staged.lstat()
            if (state.st_dev, state.st_ino) != (staged_state.st_dev, staged_state.st_ino):
                if not path.exists() and staged.exists():
                    staged.rename(path)
                raise RuntimeError(f"Manageroo uninstall target changed: {path}")
            staged_files.append((path, staged))
    except Exception:
        for path, staged in reversed(staged_files):
            if staged.exists() and not path.exists():
                staged.rename(path)
        if quarantine.exists() and not resolved_prefix.exists():
            quarantine.rename(resolved_prefix)
        raise
    shutil.rmtree(quarantine)
    for _path, staged in staged_files:
        staged.unlink()
    return [str(resolved_prefix), *[str(path) for path, _staged in staged_files]]


def uninstall_manageroo(
    *,
    prefix: Path | None = None,
    bin_dir: Path | None = None,
    codex_home: Path | None = None,
    skills_dir: Path | None = None,
    ownership_path: Path | None = None,
    components: list[str] | tuple[str, ...],
    confirmed: bool,
) -> dict[str, Any]:
    inventory = build_uninstall_inventory(
        prefix=prefix,
        bin_dir=bin_dir,
        codex_home=codex_home,
        skills_dir=skills_dir,
        ownership_path=ownership_path,
    )
    selected = list(dict.fromkeys(components))
    unknown = [item for item in selected if item not in COMPONENT_IDS]
    if unknown:
        raise ValueError(f"Unknown Manageroo uninstall component(s): {', '.join(unknown)}")
    unavailable = [item for item in selected if not inventory["by_id"][item]["removable"]]
    if unavailable:
        raise ValueError(f"Selected Manageroo component(s) are not safely removable: {', '.join(unavailable)}")
    result = {**inventory, "selected": selected, "actions": []}
    if not confirmed:
        return result
    launcher = Path(inventory["launcher"])
    if "hooks" in selected:
        action = remove_codex_continuity_hooks(
            codex_home=Path(inventory["codex_home"]),
            manageroo_command=launcher,
        )
        result["actions"].append({"component": "hooks", **action})
    if "skills" in selected:
        action = remove_manageroo_owned_skills(
            skills_dir=Path(inventory["skills_dir"]),
            ownership_path=Path(inventory["ownership_path"]),
        )
        result["actions"].append({"component": "skills", **action})
    if "state" in selected:
        removed_state: list[str] = []
        for raw_path in inventory["by_id"]["state"]["paths"]:
            path = Path(raw_path)
            if path.exists() or path.is_symlink():
                _remove_state_path(path)
                removed_state.append(str(path))
        result["actions"].append({"component": "state", "removed": removed_state})
    if "runtime" in selected:
        removed_runtime = _remove_owned_runtime(
            Path(inventory["prefix"]),
            Path(bin_dir or Path(inventory["launcher"]).parent),
        )
        result["actions"].append(
            {"component": "runtime", "removed": removed_runtime}
        )
    result["applied"] = True
    return result


def format_uninstall_inventory(inventory: dict[str, Any]) -> str:
    lines = ["Manageroo uninstall inventory", ""]
    for index, item in enumerate(inventory["components"], start=1):
        state = "removable" if item["removable"] else "not installed or not ownership-verified"
        lines.append(f"{index}) {item['label']} [{state}]")
        lines.append(f"   {item['detail']}")
        for path in item.get("paths", []):
            lines.append(f"   - {path}")
        for path in item.get("preserved_paths", []):
            lines.append(f"   - PRESERVE user-edited/unverified: {path}")
    lines.extend(["", "Recorded surrounding tools (preserved unless exact Manageroo ownership is proven):"])
    if inventory["surrounding_tools"]:
        for item in inventory["surrounding_tools"]:
            lines.append(f"- {item['name']}: {item['note']}")
    else:
        lines.append("- none recorded")
    return "\n".join(lines) + "\n"
