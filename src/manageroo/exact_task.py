from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import SafetyError, ValidationError
from .policy import validate_allowed_scope_patterns
from .reuse_policy import operator_reuse_directives
from .util import safe_repo_relative, sha256_bytes


MAX_EXTERNAL_SOURCE_BYTES = 512 * 1024
_REQUIRED_OUTCOMES_HEADING = "required outcomes"
_PLACEHOLDER_REQUIRED_OUTCOMES = frozenset(
    {
        "outcome 1",
        "outcome 2",
        "outcome 3",
        "turn the request above into working product behavior",
    }
)


def _outcome_key(value: str) -> str:
    return " ".join(value.split()).strip().rstrip(".!?").casefold()


def _brief_required_outcomes(brief: str) -> list[str]:
    outcomes: list[str] = []
    in_section = False
    for raw_line in brief.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip().casefold()
            if in_section:
                break
            in_section = heading == _REQUIRED_OUTCOMES_HEADING
            continue
        if not in_section or not line.startswith(("- ", "* ")):
            continue
        outcome = line[2:].strip()
        if outcome and _outcome_key(outcome) not in _PLACEHOLDER_REQUIRED_OUTCOMES:
            outcomes.append(outcome)
    return outcomes


def _validated_acceptance_outcomes(brief: str, proofs: list[str]) -> list[str]:
    required = _brief_required_outcomes(brief)
    if not required:
        return proofs
    required_by_key = {_outcome_key(value): value for value in required}
    proof_by_key = {_outcome_key(value): value for value in proofs}
    if len(required_by_key) != len(required):
        raise ValidationError("Product brief contains duplicate required outcomes.")
    if len(proof_by_key) != len(proofs):
        raise ValidationError("Exact-task contract contains duplicate --proof outcomes.")
    missing = [
        value for key, value in required_by_key.items() if key not in proof_by_key
    ]
    unrelated = [
        value for key, value in proof_by_key.items() if key not in required_by_key
    ]
    if missing or unrelated:
        details: list[str] = []
        if missing:
            details.append("missing: " + "; ".join(missing))
        if unrelated:
            details.append("not required by the brief: " + "; ".join(unrelated))
        raise ValidationError(
            "Exact-task --proof values must match every explicit brief required outcome ("
            + " | ".join(details)
            + ")."
        )
    return required


def _stable_source(path: Path) -> tuple[bytes, os.stat_result]:
    before = path.stat()
    if not path.is_file():
        raise ValidationError(f"Exact-task source is not a regular file: {path}")
    data = path.read_bytes()
    after = path.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(data) != after.st_size:
        raise SafetyError(f"Exact-task source changed while it was being captured: {path}")
    return data, after


def _source_record(repo: Path, raw: str) -> dict[str, Any]:
    requested = Path(raw).expanduser()
    if requested.is_absolute():
        path = requested.resolve(strict=True)
        internal = False
        repo_path = ""
        try:
            repo_path = path.relative_to(repo).as_posix()
            internal = True
        except ValueError:
            pass
    else:
        repo_path = safe_repo_relative(raw)
        path = (repo / repo_path).resolve(strict=True)
        try:
            path.relative_to(repo)
        except ValueError as exc:
            raise SafetyError(f"Exact-task source escapes the repository: {raw}") from exc
        internal = True
    data, state = _stable_source(path)
    if not internal and len(data) > MAX_EXTERNAL_SOURCE_BYTES:
        raise ValidationError(
            f"External exact-task source exceeds {MAX_EXTERNAL_SOURCE_BYTES} bytes: {path}"
        )
    if not internal:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"External exact-task source must be UTF-8 text: {path}") from exc
    return {
        "path": str(path),
        "repo_path": repo_path if internal else "",
        "internal": internal,
        "sha256": sha256_bytes(data),
        "bytes": state.st_size,
    }


def build_exact_artifacts(
    *,
    repo: Path,
    brief: str,
    contract: dict[str, Any],
    configured_gate_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Build deterministic planning artifacts for an already-specified task."""
    goal = " ".join(brief.split()).strip()
    if not goal:
        raise ValidationError("Exact-task brief cannot be empty.")
    targets = validate_allowed_scope_patterns(contract.get("targets", []))
    proofs = [str(value).strip() for value in contract.get("proofs", []) if str(value).strip()]
    if not proofs:
        raise ValidationError("Exact-task mode requires at least one --proof outcome.")
    acceptance_outcomes = _validated_acceptance_outcomes(brief, proofs)
    exclusions = [str(value).strip() for value in contract.get("exclusions", []) if str(value).strip()]
    requested_gates = [str(value).strip() for value in contract.get("gate_ids", []) if str(value).strip()]
    gate_ids = requested_gates or list(configured_gate_ids)
    unknown = sorted(set(gate_ids) - set(configured_gate_ids))
    if unknown:
        raise ValidationError("Exact-task references unknown gate IDs: " + ", ".join(unknown))
    if not gate_ids:
        raise ValidationError("Exact-task mode requires at least one configured proof gate.")
    sources = [_source_record(repo, str(value)) for value in contract.get("sources", [])]
    internal_context = [record["repo_path"] for record in sources if record["internal"]]
    for target in targets:
        if "*" not in target and (repo / target).is_file() and target not in internal_context:
            internal_context.append(target)

    directives = operator_reuse_directives(brief)
    reuse_decisions: list[dict[str, Any]] = []
    reuse_bindings: list[dict[str, Any]] = []
    if sources:
        candidate = "; ".join(record["path"] for record in sources)
        decision = "reuse-internal" if all(record["internal"] for record in sources) else "reuse-external"
        evidence = directives or ["Exact-task contract names the captured source files."]
        reuse_decisions.append(
            {
                "need": goal,
                "decision": decision,
                "candidate": candidate,
                "license": "repository/operator supplied",
                "evidence": evidence,
                "rationale": "The exact-task contract requires these sources; substitution is not allowed.",
                "risk": "low",
            }
        )
        reuse_bindings.append(
            {
                "need": goal,
                "decision": decision,
                "candidate": candidate,
                "implementation": "adapt-existing",
                "deviation": "",
            }
        )

    product = {
        "product_name": repo.name,
        "goal": goal,
        "personas": [{"name": "operator", "need": goal}],
        "capabilities": [{"id": "exact-task", "name": "Exact requested change", "description": goal}],
        "user_journeys": [
            {
                "id": "exact-task",
                "name": "Requested result",
                "steps": [goal],
                "success": acceptance_outcomes[0],
            }
        ],
        "non_goals": exclusions,
        "constraints": [
            "Edit only the exact task-owned targets.",
            "Do not substitute for named source files.",
            *exclusions,
        ],
        "acceptance_outcomes": acceptance_outcomes,
        "assumptions": [],
        "blocking_decisions": [],
    }
    system_map = {
        "modules": [
            {"name": "exact-targets", "paths": targets, "responsibility": "Only files the task may change."},
            {"name": "exact-sources", "paths": [record["path"] for record in sources], "responsibility": "Binding implementation sources."},
        ],
        "interfaces": [],
        "data_flows": [{"name": "exact-source-to-target", "steps": [*(["Read named sources"] if sources else []), "Change exact targets", "Run bound proof gates"]}],
        "trust_boundaries": [{"name": "worker-scope", "description": "Only exact targets are writable."}],
        "risks": ["A passing gate proves only its bound acceptance outcome."],
        "integration_order": ["exact-task"],
    }
    task = {
        "id": "exact-task",
        "title": "Implement the exact requested change",
        "goal": goal,
        "dependencies": [],
        "allowed_paths": targets,
        "context_paths": internal_context,
        "acceptance": acceptance_outcomes,
        "gate_ids": gate_ids,
        "risk": "medium",
        "exact_sources": sources,
        "exclusions": exclusions,
    }
    plan = {
        "summary": goal,
        "tasks": [task],
        "reuse_bindings": reuse_bindings,
        "demonstration": {
            "required": True,
            "gate_ids": gate_ids,
            "product_evidence": [
                {"outcome": outcome, "gate_ids": gate_ids} for outcome in acceptance_outcomes
            ],
        },
        "global_invariants": [
            "Only exact task-owned targets may change.",
            "Named sources must be used without substitution.",
            *exclusions,
        ],
    }
    return {
        "intake/exact-task.json": {
            "goal": goal,
            "targets": targets,
            "sources": sources,
            "exclusions": exclusions,
            "proofs": proofs,
            "brief_required_outcomes": _brief_required_outcomes(brief),
            "locked_acceptance_outcomes": acceptance_outcomes,
            "gate_ids": gate_ids,
        },
        "planning/product-model.json": product,
        "planning/reuse-report.json": {"decisions": reuse_decisions},
        "planning/system-map.json": system_map,
        "planning/task-plan.json": plan,
        "planning/plan-review.json": {
            "status": "approved",
            "summary": "Deterministic exact-task contract; no model-generated planning was used.",
            "findings": [],
        },
    }


def render_external_source_context(task: dict[str, Any]) -> str:
    sections: list[str] = []
    total = 0
    for record in task.get("exact_sources", []) or []:
        if not isinstance(record, dict) or record.get("internal"):
            continue
        path = Path(str(record.get("path") or "")).resolve(strict=True)
        data, _ = _stable_source(path)
        if sha256_bytes(data) != record.get("sha256"):
            raise SafetyError(f"Exact-task source changed after contract lock: {path}")
        total += len(data)
        if total > MAX_EXTERNAL_SOURCE_BYTES:
            raise ValidationError("Combined external exact-task source context exceeds the safe prompt limit.")
        text = data.decode("utf-8")
        fence = "MANAGEROO_EXACT_SOURCE"
        sections.append(
            f"Source: {path}\nSHA-256: {record['sha256']}\n<{fence}>\n{text}\n</{fence}>"
        )
    return "\n\n".join(sections)
