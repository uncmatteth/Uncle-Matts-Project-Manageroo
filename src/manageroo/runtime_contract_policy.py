from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_contract import (
    default_gbrain_source_id,
    ensure_default_obsidian_vault,
    gbrain_status_has_repo,
    required_stack_enabled,
    required_stack_records,
    validate_required_stack,
)


def _recompute_readiness(report: dict[str, Any]) -> dict[str, Any]:
    required = [item for item in report.get("items", []) if item.get("required", True)]
    report["ok"] = all(bool(item.get("ok")) for item in required)
    report["status"] = "READY TO RUN" if report["ok"] else "NOT READY"
    report["next_commands"] = list(
        dict.fromkeys(
            str(item.get("next") or "")
            for item in report.get("items", [])
            if not item.get("ok") and item.get("next")
        )
    )
    return report


def install_runtime_contract_policy(
    orchestrator_module: Any,
    readiness_module: Any,
    release_ready_module: Any,
) -> None:
    orchestrator_class = orchestrator_module.Orchestrator
    if getattr(orchestrator_class, "_manageroo_runtime_contract_installed", False):
        return

    def validate_stack(self: Any) -> None:
        validate_required_stack(self.config)

    orchestrator_class._validate_required_stack_configuration = validate_stack
    orchestrator_class._manageroo_runtime_contract_installed = True

    original_readiness = readiness_module.readiness

    def readiness(repo_path: Path, *, require_gbrain: bool = False) -> dict[str, Any]:
        report = original_readiness(repo_path, require_gbrain=require_gbrain)
        repo_text = str(report.get("repo") or "").strip()
        if not repo_text:
            return report
        repo = Path(repo_text).expanduser().resolve(strict=False)
        try:
            config = readiness_module.load_config(repo)
        except Exception:
            return report
        if not required_stack_enabled(config):
            return report
        existing_names = {
            str(item.get("name") or "") for item in report.get("items", [])
        }
        for record in required_stack_records(config):
            if record["name"] in existing_names:
                continue
            report.setdefault("items", []).append(
                {
                    "name": record["name"],
                    "ok": bool(record["ok"]),
                    "detail": str(record["detail"]),
                    "next": str(record["next"]),
                    "required": True,
                    "severity": "required",
                }
            )
        return _recompute_readiness(report)

    readiness_module.readiness = readiness
    # release_ready imported readiness before policy installation. Rebind it so
    # release checks cannot drift from the public project-run diagnostic.
    release_ready_module.readiness = readiness


def install_runtime_cli_policy(cli_module: Any) -> None:
    if getattr(cli_module, "_manageroo_runtime_cli_contract_installed", False):
        return
    original = cli_module.configure_integrations

    def configure_integrations(repo: Path, *args: Any, **kwargs: Any) -> dict[str, Any]:
        # setup/solo omit `full`; real product-run adapters must configure the
        # complete required stack. The deterministic mock harness intentionally
        # remains independent of host integrations.
        try:
            config = cli_module.load_config(Path(repo))
        except Exception:
            config = {}
        implicit_public_setup = "full" not in kwargs
        if implicit_public_setup and required_stack_enabled(config):
            kwargs["full"] = True
            kwargs["gbrain"] = True
            kwargs["gitnexus"] = True
        if kwargs.get("full") and kwargs.get("obsidian_vault") is None:
            current = str(
                config.get("integrations", {}).get("obsidian_vault") or ""
            ).strip()
            if current and Path(current).expanduser().is_dir():
                kwargs["obsidian_vault"] = Path(current)
            else:
                vault, export = ensure_default_obsidian_vault(Path(repo))
                kwargs["obsidian_vault"] = vault
                kwargs.setdefault("obsidian_export_folder", export)
        report = original(repo, *args, **kwargs)
        if implicit_public_setup and required_stack_enabled(config):
            current_status = cli_module.gbrain_setup_status()
            if gbrain_status_has_repo(current_status, Path(repo)):
                source_report = current_status
            else:
                source_report = cli_module.gbrain_setup_status(
                    source_id=default_gbrain_source_id(Path(repo)),
                    source_path=Path(repo),
                    apply=True,
                    sync=True,
                )
            report = dict(report)
            report["gbrain_repo_source"] = source_report
            if not source_report.get("ok") or not gbrain_status_has_repo(
                source_report, Path(repo)
            ):
                report["ok"] = False
                next_commands = list(source_report.get("next_commands", []) or [])
                if next_commands:
                    report["next_command"] = str(next_commands[0])
        return report

    cli_module.configure_integrations = configure_integrations
    cli_module._manageroo_runtime_cli_contract_installed = True
