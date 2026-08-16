from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .util import safe_repo_relative


REQUIRED_STACK_CAPABILITIES = (
    "gbrain",
    "gitnexus",
    "autoreview",
    "clawpatch",
    "obsidian-vault",
)

_REQUIRED_COMMAND_GROUPS: dict[str, tuple[str, ...]] = {
    "gbrain": ("gbrain_search_command", "gbrain_capture_command"),
    "gitnexus": ("gitnexus_analyze_command", "gitnexus_query_command"),
    "autoreview": ("autoreview_command",),
    "clawpatch": ("clawpatch_command",),
}


def required_stack_enabled(config: dict[str, Any]) -> bool:
    """Return whether the selected worker is a real product-run adapter."""

    return str(config.get("agent", {}).get("adapter", "auto")) != "mock"


def _command_executable(command: Any) -> tuple[bool, str]:
    if not isinstance(command, list) or not command or not str(command[0]).strip():
        return False, "not configured"
    executable = str(command[0]).strip()
    candidate = Path(executable).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        try:
            ok = candidate.is_file() and (
                os.name == "nt" or os.access(candidate, os.X_OK)
            )
        except OSError:
            ok = False
        return ok, str(candidate)
    resolved = shutil.which(executable)
    return bool(resolved), resolved or executable


def default_obsidian_vault(repo: Path) -> Path:
    """Return a deterministic Manageroo-owned vault outside the product repo."""

    explicit = os.environ.get("MANAGEROO_DEFAULT_OBSIDIAN_VAULT_ROOT", "").strip()
    if explicit:
        root = Path(explicit).expanduser()
    elif os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or Path.home() / "AppData" / "Local"
        )
        root = base / "manageroo" / "obsidian-vaults"
    else:
        base = Path(
            os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
        )
        root = base / "manageroo" / "obsidian-vaults"
    identity = hashlib.sha256(
        os.fsencode(str(repo.expanduser().resolve(strict=False)))
    ).hexdigest()
    return root / identity


def default_gbrain_source_id(repo: Path) -> str:
    name = "-".join(
        part for part in repo.name.casefold().replace("_", "-").split("-") if part
    )
    safe = "".join(char if char.isalnum() or char == "-" else "-" for char in name)
    safe = safe.strip("-") or "project"
    identity = hashlib.sha256(
        os.fsencode(str(repo.expanduser().resolve(strict=False)))
    ).hexdigest()[:12]
    return f"manageroo-{safe[:40]}-{identity}"


def gbrain_status_has_repo(report: dict[str, Any], repo: Path) -> bool:
    expected = repo.expanduser().resolve(strict=False)
    sources = report.get("status", {}).get("sources", [])
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict) or not source.get("path"):
            continue
        try:
            if Path(str(source["path"])).expanduser().resolve(strict=True) == expected.resolve(
                strict=True
            ):
                return True
        except (OSError, RuntimeError, ValueError):
            continue
    return False


def ensure_default_obsidian_vault(
    repo: Path, *, export_folder: str = "MANAGEROO"
) -> tuple[Path, str]:
    export = safe_repo_relative(export_folder)
    vault = default_obsidian_vault(repo)
    vault.mkdir(parents=True, exist_ok=True, mode=0o700)
    (vault / export).mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(vault, 0o700)
        os.chmod(vault / export, 0o700)
    return vault.resolve(strict=True), export


def required_stack_records(config: dict[str, Any]) -> list[dict[str, Any]]:
    integrations = config.get("integrations", {})
    records: list[dict[str, Any]] = []
    for capability, keys in _REQUIRED_COMMAND_GROUPS.items():
        missing_configuration: list[str] = []
        unavailable: list[str] = []
        resolved: list[str] = []
        for key in keys:
            command = integrations.get(key)
            ok, detail = _command_executable(command)
            if not isinstance(command, list) or not command:
                missing_configuration.append(key)
            elif not ok:
                unavailable.append(f"{key} ({detail})")
            else:
                resolved.append(detail)
        ok = not missing_configuration and not unavailable
        detail_parts: list[str] = []
        if missing_configuration:
            detail_parts.append("missing config: " + ", ".join(missing_configuration))
        if unavailable:
            detail_parts.append("unavailable executable: " + ", ".join(unavailable))
        if ok:
            detail_parts.append("configured: " + ", ".join(resolved))
        records.append(
            {
                "id": capability,
                "name": f"required stack:{capability}",
                "ok": ok,
                "detail": "; ".join(detail_parts),
                "next": "manageroo integrations configure --full",
            }
        )

    vault_text = str(integrations.get("obsidian_vault") or "").strip()
    export_text = str(integrations.get("obsidian_export_folder") or "MANAGEROO").strip()
    vault = Path(vault_text).expanduser() if vault_text else None
    export_ok = False
    detail = "obsidian_vault is not configured"
    if vault is not None:
        try:
            export = safe_repo_relative(export_text)
            resolved_vault = vault.resolve(strict=True)
            export_path = (resolved_vault / export).resolve(strict=True)
            export_path.relative_to(resolved_vault)
            export_ok = resolved_vault.is_dir() and export_path.is_dir()
            detail = (
                f"configured: {resolved_vault} / {export}"
                if export_ok
                else f"vault or export folder is missing: {resolved_vault} / {export}"
            )
        except (OSError, ValueError, ValidationError):
            detail = "obsidian vault or export folder is invalid"
        except Exception:
            detail = "obsidian vault or export folder is invalid"
    records.append(
        {
            "id": "obsidian-vault",
            "name": "required stack:obsidian-vault",
            "ok": export_ok,
            "detail": detail,
            "next": "manageroo integrations configure --full --obsidian-vault PATH",
        }
    )
    return records


def missing_required_stack(config: dict[str, Any]) -> list[str]:
    if not required_stack_enabled(config):
        return []
    return [record["id"] for record in required_stack_records(config) if not record["ok"]]


def validate_required_stack(config: dict[str, Any]) -> None:
    missing = missing_required_stack(config)
    if missing:
        raise ValidationError(
            "The required Manageroo stack is not ready: "
            + ", ".join(missing)
            + ". Run `manageroo integrations configure --full` and rerun `manageroo ready`."
        )
