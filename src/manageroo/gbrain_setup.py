from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


GBRAIN_ACTIVATION_GUIDANCE = [
    "gbrain search modes",
    "gbrain onboard --check --json",
    "gbrain features --json",
    "gbrain integrations list",
    "gbrain autopilot --install",
    "gbrain dream --json",
]


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


def summarize_search_modes(output: str) -> dict[str, Any]:
    active = ""
    for line in output.splitlines():
        prefix = "Search mode (active):"
        if line.startswith(prefix):
            active = line.removeprefix(prefix).strip()
            break
    return {"ok": bool(active), "active_mode": active}


def summarize_recommendation_json(output: str) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"ok": False, "error": "JSON probe did not return JSON"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "JSON probe returned non-object JSON"}
    recommendations = payload.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    return {
        "ok": True,
        "recommendation_count": len(recommendations),
        "recommendations": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "command": item.get("command"),
                "apply_policy": item.get("apply_policy"),
                "auto_fixable": item.get("auto_fixable"),
            }
            for item in recommendations
            if isinstance(item, dict)
        ],
        "summary": summary,
        "brain_score": payload.get("brain_score"),
    }


def summarize_integrations_list(output: str) -> dict[str, Any]:
    configured: list[str] = []
    available: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("Run "):
            continue
        parts = stripped.split()
        if not parts:
            continue
        name = parts[0]
        if "CONFIGURED" in stripped:
            configured.append(name)
        elif "AVAILABLE" in stripped:
            available.append(name)
    return {
        "ok": bool(configured or available or "integrations" in output.lower()),
        "configured": configured,
        "available": available,
        "configured_count": len(configured),
        "available_count": len(available),
    }


def gbrain_activation_status(gbrain: str, runner=run_probe) -> dict[str, Any]:
    probes = {
        "search_modes": runner([gbrain, "search", "modes"], 30),
        "onboard": runner([gbrain, "onboard", "--check", "--json"], 120),
        "features": runner([gbrain, "features", "--json"], 120),
        "integrations": runner([gbrain, "integrations", "list"], 60),
        "check_update": runner([gbrain, "check-update", "--json"], 60),
    }
    search = summarize_search_modes(probes["search_modes"].get("output", "")) if probes["search_modes"].get("ok") else {
        "ok": False,
        "error": probes["search_modes"].get("output") or probes["search_modes"].get("error") or "search mode probe failed",
    }
    onboard = summarize_recommendation_json(probes["onboard"].get("output", "")) if probes["onboard"].get("ok") else {
        "ok": False,
        "error": probes["onboard"].get("output") or probes["onboard"].get("error") or "onboard probe failed",
    }
    features = summarize_recommendation_json(probes["features"].get("output", "")) if probes["features"].get("ok") else {
        "ok": False,
        "error": probes["features"].get("output") or probes["features"].get("error") or "features probe failed",
    }
    integrations = summarize_integrations_list(probes["integrations"].get("output", "")) if probes["integrations"].get("ok") else {
        "ok": False,
        "error": probes["integrations"].get("output") or probes["integrations"].get("error") or "integrations probe failed",
    }
    update = summarize_recommendation_json(probes["check_update"].get("output", "")) if probes["check_update"].get("ok") else {
        "ok": False,
        "error": probes["check_update"].get("output") or probes["check_update"].get("error") or "update probe failed",
    }
    next_commands: list[str] = []
    for key, command in (
        ("search_modes", "gbrain search modes"),
        ("onboard", "gbrain onboard --check --json"),
        ("features", "gbrain features --json"),
        ("integrations", "gbrain integrations list"),
    ):
        if not probes[key].get("ok"):
            next_commands.append(command)
    for recommendation in onboard.get("recommendations", []):
        command = recommendation.get("command")
        if command and command not in next_commands:
            next_commands.append(command)
    for recommendation in features.get("recommendations", []):
        command = recommendation.get("command")
        if command and command not in next_commands:
            next_commands.append(command)
    setup_choices = [
        "gbrain integrations show retrieval-reflex",
        "gbrain integrations show credential-gateway",
        "gbrain integrations show email-to-brain",
        "gbrain integrations show calendar-to-brain",
        "gbrain integrations show x-to-brain",
        "gbrain integrations show meeting-sync",
        "gbrain integrations show ngrok-tunnel",
        "gbrain integrations show restart-sweep",
    ]
    return {
        "ok": bool(search.get("ok") and onboard.get("ok") and features.get("ok") and integrations.get("ok")),
        "probes": {name: safe_probe_record(probe) for name, probe in probes.items()},
        "search": search,
        "onboard": onboard,
        "features": features,
        "integrations": integrations,
        "update": update,
        "next_commands": next_commands,
        "recurring_job_commands": [
            "gbrain autopilot --install",
            "gbrain dream --json",
            "gbrain sync --install-cron",
        ],
        "integration_setup_choices": setup_choices,
        "rule": "Use GBrain's own activation surfaces; do not silently choose paid/hosted data lanes for the operator.",
    }


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
    activation = gbrain_activation_status(gbrain)
    if summary.get("ok") and summary.get("source_count") == 0:
        next_commands.append("gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder")
        next_commands.append("gbrain sync --source YOUR_SOURCE_ID --json --yes")
    actions_ok = all(action.get("ok") for action in actions)
    has_sources = bool(summary.get("ok") and summary.get("source_count", 0) > 0)
    return {
        "ok": bool(summary.get("ok")) and has_sources and actions_ok,
        "installed": True,
        "path": gbrain,
        "config": config_summary,
        "config_probe": safe_probe_record(config_probe),
        "status": summary,
        "activation": activation,
        "actions": actions,
        "next_commands": [*next_commands, *activation.get("next_commands", [])],
        "rule": "No broad scan. Add only folders the operator chooses.",
    }


def format_gbrain_setup(report: dict[str, Any]) -> str:
    if not report.get("installed"):
        return "GBRAIN: NOT INSTALLED\nNext: " + report["next_commands"][0] + "\n"
    status = report.get("status", {})
    has_sources = bool(status.get("source_count", 0) > 0)
    lines = [f"GBRAIN: {'OK' if status.get('ok') and has_sources else 'ACTION'}"]
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
    activation = report.get("activation", {})
    if activation:
        search = activation.get("search", {})
        if search.get("active_mode"):
            lines.append(f"Search mode: {search['active_mode']}")
        onboard = activation.get("onboard", {})
        features = activation.get("features", {})
        integrations = activation.get("integrations", {})
        if onboard.get("ok"):
            lines.append(f"Onboard recommendations: {onboard.get('recommendation_count', 0)}")
        if features.get("ok"):
            lines.append(f"Feature recommendations: {features.get('recommendation_count', 0)}")
        if integrations.get("ok"):
            lines.append(
                "Integrations: "
                f"{integrations.get('configured_count', 0)} configured, "
                f"{integrations.get('available_count', 0)} available"
            )
        for command in activation.get("recurring_job_commands", []):
            lines.append(f"Recurring: {command}")
        for command in activation.get("integration_setup_choices", []):
            lines.append(f"Choice: {command}")
    for action in report.get("actions", []):
        label = "OK" if action.get("ok") else "FAILED"
        lines.append(f"{label}: {' '.join(action.get('argv', []))}")
        if not action.get("ok") and action.get("output"):
            lines.append(action["output"])
    for command in report.get("next_commands", []):
        lines.append(f"Next: {command}")
    lines.append(report.get("rule", ""))
    return "\n".join(item for item in lines if item) + "\n"
