from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .util import safe_repo_relative


# These integrations enrich a run, but Manageroo's portable controller does not
# depend on all of them merely to perform an ordinary isolated coding job.
ENHANCED_STACK_CAPABILITIES = (
    "gbrain",
    "gitnexus",
    "autoreview",
    "clawpatch",
    "obsidian-vault",
)
# Backward-compatible public name. "Required" now means explicitly required by
# a selected operation/configuration, not globally required for every real run.
REQUIRED_STACK_CAPABILITIES = ENHANCED_STACK_CAPABILITIES

_COMMAND_GROUPS: dict[str, tuple[str, ...]] = {
    "gbrain": ("gbrain_search_command", "gbrain_capture_command"),
    "gitnexus": ("gitnexus_analyze_command", "gitnexus_query_command"),
    "autoreview": ("autoreview_command",),
    "clawpatch": ("clawpatch_command",),
}


def required_stack_enabled(config: dict[str, Any]) -> bool:
    """Return whether host capability diagnostics apply to this adapter."""

    return str(config.get("agent", {}).get("adapter", "auto")) != "mock"


def _configured_required_capabilities(
    config: dict[str, Any], explicit: Iterable[str] = ()
) -> tuple[str, ...]:
    configured = config.get("runtime", {}).get("required_capabilities", [])
    values = [*configured, *explicit] if isinstance(configured, list) else list(explicit)
    unknown = sorted(
        {
            str(value).strip()
            for value in values
            if str(value).strip() and str(value).strip() not in ENHANCED_STACK_CAPABILITIES
        }
    )
    if unknown:
        raise ValidationError(
            "Unknown Manageroo runtime capabilities: " + ", ".join(unknown)
        )
    return tuple(
        capability
        for capability in ENHANCED_STACK_CAPABILITIES
        if capability in {str(value).strip() for value in values}
    )


def required_capability_ids(
    config: dict[str, Any], explicit: Iterable[str] = ()
) -> tuple[str, ...]:
    if not required_stack_enabled(config):
        return ()
    return _configured_required_capabilities(config, explicit)


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


def _command_capability_record(
    capability: str,
    keys: tuple[str, ...],
    integrations: dict[str, Any],
    *,
    required: bool,
) -> dict[str, Any]:
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
        detail_parts.append("not configured: " + ", ".join(missing_configuration))
    if unavailable:
        detail_parts.append("unavailable executable: " + ", ".join(unavailable))
    if ok:
        detail_parts.append("available: " + ", ".join(resolved))
    return {
        "id": capability,
        "name": f"runtime capability:{capability}",
        "ok": ok,
        "available": ok,
        "required": required,
        "detail": "; ".join(detail_parts),
        "next": "manageroo integrations configure --full",
    }


def _obsidian_record(
    integrations: dict[str, Any], *, required: bool
) -> dict[str, Any]:
    vault_text = str(integrations.get("obsidian_vault") or "").strip()
    export_text = str(integrations.get("obsidian_export_folder") or "MANAGEROO").strip()
    vault = Path(vault_text).expanduser() if vault_text else None
    export_ok = False
    detail = "not configured"
    if vault is not None:
        try:
            export = safe_repo_relative(export_text)
            resolved_vault = vault.resolve(strict=True)
            export_path = (resolved_vault / export).resolve(strict=True)
            export_path.relative_to(resolved_vault)
            export_ok = resolved_vault.is_dir() and export_path.is_dir()
            detail = (
                f"available: {resolved_vault} / {export}"
                if export_ok
                else f"vault or export folder is missing: {resolved_vault} / {export}"
            )
        except (OSError, ValueError, ValidationError):
            detail = "vault or export folder is invalid"
    return {
        "id": "obsidian-vault",
        "name": "runtime capability:obsidian-vault",
        "ok": export_ok,
        "available": export_ok,
        "required": required,
        "detail": detail,
        "next": "manageroo integrations configure --full --obsidian-vault PATH",
    }


def runtime_capability_records(
    config: dict[str, Any], *, required_capabilities: Iterable[str] = ()
) -> list[dict[str, Any]]:
    required = set(required_capability_ids(config, required_capabilities))
    integrations = config.get("integrations", {})
    records = [
        _command_capability_record(
            capability,
            keys,
            integrations,
            required=capability in required,
        )
        for capability, keys in _COMMAND_GROUPS.items()
    ]
    records.append(
        _obsidian_record(integrations, required="obsidian-vault" in required)
    )
    return records


def required_stack_records(
    config: dict[str, Any], *, required_capabilities: Iterable[str] = ()
) -> list[dict[str, Any]]:
    """Backward-compatible alias for the authoritative capability report."""

    return runtime_capability_records(
        config, required_capabilities=required_capabilities
    )


def missing_required_stack(
    config: dict[str, Any], *, required_capabilities: Iterable[str] = ()
) -> list[str]:
    return [
        record["id"]
        for record in runtime_capability_records(
            config, required_capabilities=required_capabilities
        )
        if record["required"] and not record["available"]
    ]


def validate_required_stack(
    config: dict[str, Any], *, required_capabilities: Iterable[str] = ()
) -> None:
    missing = missing_required_stack(
        config, required_capabilities=required_capabilities
    )
    if missing:
        raise ValidationError(
            "The requested Manageroo operation requires unavailable capabilities: "
            + ", ".join(missing)
            + ". Configure only the named capability, or run "
            "`manageroo integrations configure --full` for the enhanced stack."
        )
