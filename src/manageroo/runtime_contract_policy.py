from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_contract import (
    default_gbrain_source_id,
    ensure_default_obsidian_vault,
    gbrain_status_has_repo,
    required_capability_ids,
    required_stack_enabled,
    runtime_capability_records,
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
            if item.get("required", True) and not item.get("ok") and item.get("next")
        )
    )
    return report


def _orchestrator_required_capabilities(orchestrator: Any) -> tuple[str, ...]:
    explicit = getattr(orchestrator, "required_runtime_capabilities", ())
    if callable(explicit):
        explicit = explicit()
    if not isinstance(explicit, (list, tuple, set, frozenset)):
        explicit = ()
    return required_capability_ids(orchestrator.config, explicit)


def install_runtime_contract_policy(
    orchestrator_module: Any,
    readiness_module: Any,
    release_ready_module: Any,
) -> None:
    orchestrator_class = orchestrator_module.Orchestrator
    if getattr(orchestrator_class, "_manageroo_runtime_contract_installed", False):
        return

    def validate_stack(self: Any) -> None:
        required = _orchestrator_required_capabilities(self)
        records = runtime_capability_records(
            self.config, required_capabilities=required
        )
        self.runtime_capability_report = {
            "required": list(required),
            "records": records,
            "enhanced_stack_available": [
                record["id"] for record in records if record["available"]
            ],
            "enhanced_stack_unavailable": [
                record["id"] for record in records if not record["available"]
            ],
        }
        writer = getattr(self, "_write_or_reuse_json", None)
        if callable(writer):
            writer(
                "verification/runtime-capabilities.json",
                self.runtime_capability_report,
                lock=True,
            )
        validate_required_stack(
            self.config, required_capabilities=required
        )

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
        explicit = ("gbrain",) if require_gbrain else ()
        records = runtime_capability_records(
            config, required_capabilities=explicit
        )
        existing_names = {
            str(item.get("name") or "") for item in report.get("items", [])
        }
        for record in records:
            if record["name"] in existing_names:
                continue
            report.setdefault("items", []).append(
                {
                    "name": record["name"],
                    "ok": bool(record["available"]),
                    "detail": str(record["detail"]),
                    "next": str(record["next"]),
                    "required": bool(record["required"]),
                    "severity": "required" if record["required"] else "optional",
                }
            )
        report["runtime_capabilities"] = {
            "available": [record["id"] for record in records if record["available"]],
            "unavailable": [record["id"] for record in records if not record["available"]],
            "required": [record["id"] for record in records if record["required"]],
        }
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
        try:
            config = cli_module.load_config(Path(repo))
        except Exception:
            config = {}
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
        # Exact GBrain source mapping is needed only when that optional lane was
        # selected/configured for this setup call.
        if required_stack_enabled(config) and bool(kwargs.get("gbrain")):
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
