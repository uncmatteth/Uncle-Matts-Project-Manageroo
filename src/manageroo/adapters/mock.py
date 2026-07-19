from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import SafetyError
from ..schema import load_schema, validate
from ..util import atomic_write_json, safe_repo_relative


class MockAdapter(AgentAdapter):
    """Deterministic adapter used by the harness's own tests and simulation."""

    def doctor(self, cwd: Path) -> dict:
        return {"ok": True, "adapter": "mock", "version": "deterministic-test-double"}

    def run(self, request: AgentRequest) -> AgentResponse:
        role = request.role
        metadata = request.metadata
        if role == "product-analyst":
            data = {
                "product_name": "Fixture Product",
                "goal": "Satisfy the supplied product brief.",
                "personas": [{"name": "operator", "need": "a working product"}],
                "capabilities": [{
                    "id": "CAP-001",
                    "name": "Requested capability",
                    "description": "Implement the requested behavior.",
                }],
                "user_journeys": [{
                    "id": "J-001",
                    "name": "Primary journey",
                    "steps": ["perform request"],
                    "success": "observable success",
                }],
                "non_goals": [],
                "constraints": ["Preserve existing behavior outside the task."],
                "acceptance_outcomes": ["Configured verification gates pass."],
                "assumptions": [],
                "blocking_decisions": [],
            }
        elif role == "reuse-researcher":
            data = {
                "decisions": [{
                    "need": "fixture implementation",
                    "decision": "reuse-internal",
                    "candidate": "existing repository conventions",
                    "license": "repository-owned",
                    "evidence": ["repository inventory"],
                    "rationale": "Avoid unnecessary external dependencies.",
                    "risk": "low",
                }]
            }
        elif role == "repository-mapper":
            data = {
                "chunk_id": metadata.get("chunk_id", "chunk-1"),
                "modules": [{
                    "name": "fixture",
                    "paths": metadata.get("paths", []),
                    "responsibility": "fixture code",
                }],
                "interfaces": [],
                "data_flows": [],
                "trust_boundaries": [],
                "risks": [],
            }
        elif role == "map-reducer":
            data = {
                "modules": [{
                    "name": "fixture",
                    "paths": metadata.get("all_paths", []),
                    "responsibility": "fixture code",
                }],
                "interfaces": [],
                "data_flows": [],
                "trust_boundaries": [],
                "risks": [],
                "integration_order": ["TASK-001"],
            }
        elif role == "plan-compiler":
            target = metadata.get("fixture_target", "manageroo_fixture.txt")
            gate_ids = metadata.get("gate_ids", ["fixture-check"])
            data = {
                "summary": "Implement the brief as one bounded task.",
                "tasks": [{
                    "id": "TASK-001",
                    "title": "Implement requested fixture change",
                    "goal": "Create the requested observable fixture.",
                    "dependencies": [],
                    "allowed_paths": [target],
                    "context_paths": [],
                    "acceptance": ["required gates pass"],
                    "gate_ids": gate_ids,
                    "risk": "low",
                }],
                "demonstration": {
                    "required": False,
                    "gate_ids": gate_ids,
                    "product_evidence": [{
                        "outcome": "Configured verification gates pass.",
                        "gate_ids": gate_ids,
                    }],
                },
                "global_invariants": ["Do not edit outside task scope."],
            }
        elif role == "plan-reviewer":
            data = {"status": "approved", "summary": "Plan is bounded.", "findings": []}
        elif role in {"implementer", "repairer"}:
            target = metadata.get("task", {}).get("allowed_paths", ["manageroo_fixture.txt"])[0]
            relative = safe_repo_relative(str(target))
            root = request.cwd.expanduser().resolve()
            target_path = (root / relative).resolve()
            try:
                target_path.relative_to(root)
            except ValueError as exc:
                raise SafetyError(f"Mock adapter target escapes working tree: {target}") from exc
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text("MANAGEROO deterministic fixture completed\n", encoding="utf-8")
            data = {
                "status": "implemented",
                "summary": "Fixture change implemented.",
                "files_changed": [relative],
                "commands_run": [],
                "risks": [],
                "scope_expansion_requested": [],
            }
        elif role == "reviewer":
            data = {"status": "approved", "summary": "No blocking defects found.", "findings": []}
        else:
            raise RuntimeError(f"Mock adapter does not implement role {role!r}")
        validate(data, load_schema(request.schema_path))
        atomic_write_json(request.output_path, data)
        return AgentResponse(role=role, data=data, raw_text="", command=["mock"])
