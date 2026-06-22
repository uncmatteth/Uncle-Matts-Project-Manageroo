from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def run_probe(argv: list[str], timeout_seconds: int = 60) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            timeout=timeout_seconds,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "argv": argv,
            "output": (result.stdout or "").strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "argv": argv, "error": str(exc), "output": ""}


def safe_probe_record(probe: dict[str, Any]) -> dict[str, Any]:
    record = {
        "ok": probe.get("ok"),
        "exit_code": probe.get("exit_code"),
        "argv": probe.get("argv", []),
    }
    if not probe.get("ok"):
        record["error"] = probe.get("error")
        record["output"] = probe.get("output", "")
    return record


def summarize_sync_status(output: str) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"ok": False, "error": "gbrain status did not return JSON"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "gbrain status returned non-object JSON"}
    sync = payload.get("sync")
    if not isinstance(sync, dict):
        return {"ok": False, "error": "gbrain status did not include sync data"}
    sources = sync.get("sources")
    if not isinstance(sources, list):
        return {"ok": False, "error": "gbrain sync data did not include sources"}
    coverages = [
        float(source["embedding_coverage_pct"])
        for source in sources
        if isinstance(source, dict) and source.get("embedding_coverage_pct") is not None
    ]
    return {
        "ok": True,
        "sources": [
            {
                "id": source.get("source_id"),
                "name": source.get("name"),
                "path": source.get("local_path"),
                "pages": source.get("pages"),
                "chunks_total": source.get("chunks_total"),
                "chunks_unembedded": source.get("chunks_unembedded"),
                "embedding_coverage_pct": source.get("embedding_coverage_pct"),
            }
            for source in sources
            if isinstance(source, dict)
        ],
        "source_count": len(sources),
        "chunks_total": sum(
            int(source.get("chunks_total") or 0)
            for source in sources
            if isinstance(source, dict)
        ),
        "chunks_unembedded": sum(
            int(source.get("chunks_unembedded") or 0)
            for source in sources
            if isinstance(source, dict)
        ),
        "embedding_coverage_min_pct": min(coverages) if coverages else None,
        "unacknowledged_failures": sync.get("unacknowledged_failures"),
    }


def summarize_gbrain_config(output: str) -> dict[str, str]:
    config: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        key = key.strip()
        if key in {"engine", "embedding_model", "embedding_dimensions", "schema_pack"}:
            config[key] = value.strip()
    return config


def gbrain_setup_status(
    *,
    source_id: str | None = None,
    source_path: Path | None = None,
    apply: bool = False,
    sync: bool = False,
) -> dict[str, Any]:
    gbrain = shutil.which("gbrain")
    if not gbrain:
        return {
            "ok": False,
            "installed": False,
            "next_commands": [
                "Install GBrain first, then rerun `manageroo gbrain-setup`.",
            ],
        }

    actions: list[dict[str, Any]] = []
    next_commands: list[str] = []
    if source_id or source_path:
        if not source_id or not source_path:
            raise ValueError("--source-id and --path must be provided together.")
        source_path = source_path.expanduser().resolve()
        add_argv = [gbrain, "sources", "add", source_id, "--path", str(source_path)]
        sync_argv = [gbrain, "sync", "--source", source_id, "--json", "--yes"]
        if apply:
            actions.append(run_probe(add_argv))
            if sync:
                actions.append(run_probe(sync_argv, timeout_seconds=300))
        else:
            next_commands.append(" ".join(add_argv))
            if sync:
                next_commands.append(" ".join(sync_argv))

    config_probe = run_probe([gbrain, "config", "show"])
    config_summary = (
        summarize_gbrain_config(config_probe.get("output", ""))
        if config_probe.get("ok")
        else {}
    )
    status_probe = run_probe([gbrain, "status", "--json", "--section", "sync"])
    summary = summarize_sync_status(status_probe.get("output", "")) if status_probe.get("ok") else {
        "ok": False,
        "error": status_probe.get("error") or status_probe.get("output") or "gbrain status failed",
    }
    if summary.get("ok") and summary.get("source_count") == 0:
        next_commands.append("gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder")
        next_commands.append("gbrain sync --source YOUR_SOURCE_ID --json --yes")
    actions_ok = all(action.get("ok") for action in actions)
    return {
        "ok": bool(summary.get("ok")) and actions_ok,
        "installed": True,
        "path": gbrain,
        "config": config_summary,
        "config_probe": safe_probe_record(config_probe),
        "status": summary,
        "actions": actions,
        "next_commands": next_commands,
        "rule": "No broad scan. Add only folders the operator chooses.",
    }


def format_gbrain_setup(report: dict[str, Any]) -> str:
    if not report.get("installed"):
        return "GBRAIN: NOT INSTALLED\nNext: " + report["next_commands"][0] + "\n"
    status = report.get("status", {})
    lines = [f"GBRAIN: {'OK' if status.get('ok') else 'ACTION'}"]
    if status.get("ok"):
        config = report.get("config", {})
        for key in ("engine", "embedding_model", "embedding_dimensions", "schema_pack"):
            if config.get(key):
                lines.append(f"{key}: {config[key]}")
        lines.append(f"Sources: {status.get('source_count', 0)}")
        for source in status.get("sources", []):
            source_id = source.get("id") or source.get("name") or "unknown"
            source_path = source.get("path") or "no local path"
            lines.append(f"- {source_id}: {source_path}")
        lines.append(f"Chunks: {status.get('chunks_total', 0)}")
        lines.append(f"Unembedded chunks: {status.get('chunks_unembedded', 0)}")
        if status.get("embedding_coverage_min_pct") is not None:
            lines.append(f"Minimum embedding coverage: {status['embedding_coverage_min_pct']}%")
    else:
        lines.append(f"Problem: {status.get('error', 'status unavailable')}")
    for action in report.get("actions", []):
        label = "OK" if action.get("ok") else "FAILED"
        lines.append(f"{label}: {' '.join(action.get('argv', []))}")
        if not action.get("ok") and action.get("output"):
            lines.append(action["output"])
    for command in report.get("next_commands", []):
        lines.append(f"Next: {command}")
    lines.append(report.get("rule", ""))
    return "\n".join(item for item in lines if item) + "\n"
