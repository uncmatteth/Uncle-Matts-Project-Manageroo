from __future__ import annotations

import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

from .context import ContextCompiler, ContextRequest
from .errors import GateFailure, SafetyError, ValidationError
from .integrations import ObsidianIntegration
from .inventory import build_inventory, inventory_summary
from .managed_contract_common import EXECUTION_INTENT_READ_ONLY, _load_request_metadata
from .report import write_report
from .review import inventory_hashes, validate_review_evidence
from .state import Phase
from .util import atomic_write_json, utc_now


def _audit_chunk_tokens(config: dict[str, Any]) -> int:
    context = config["context"]
    usable = int(context["max_input_tokens"]) - int(context["reserve_output_tokens"])
    return max(
        1_000,
        min(int(context["map_chunk_tokens"]) // 2, max(1_000, usable // 3)),
    )


def _read_only_audit(
    self: Any,
    *,
    brief: str,
    inventory: list[dict[str, Any]],
    system_map: dict[str, Any],
    memory: dict[str, Any],
    external_intelligence: dict[str, Any],
    orchestrator_module: Any,
) -> dict[str, Any]:
    existing = self._artifact_json("review/review.json")
    if isinstance(existing, dict):
        return existing
    assert self.workspace is not None
    chunks = ContextCompiler.partition_paths(
        inventory,
        max_tokens=_audit_chunk_tokens(self.config),
    ) or [[]]
    plan = {
        "execution_intent": EXECUTION_INTENT_READ_ONLY,
        "source_mutation_authorized": False,
        "chunk_count": len(chunks),
        "chunks": [[str(item["path"]) for item in chunk] for chunk in chunks],
        "rule": (
            "Review the entire current repository in bounded read-only slices. "
            "Every reported defect must cite exact current source evidence."
        ),
    }
    self._write_or_reuse_json("planning/audit-plan.json", plan, lock=True)
    names = [
        self._next_call_name(f"read-only-auditor-{index}")
        for index in range(1, len(chunks) + 1)
    ]

    def audit_chunk(offset: int, chunk: list[dict[str, Any]]) -> dict[str, Any]:
        index = offset + 1
        chunk_paths = [str(item["path"]) for item in chunk]
        requests = [
            ContextRequest(
                path=str(item["path"]),
                reason="Current repository source under read-only audit.",
                required=True,
                priority=100,
                mode=(
                    "summary"
                    if item.get("content_kind") == "media"
                    or int(item.get("estimated_tokens", 0))
                    > int(self.config["context"]["max_single_file_tokens"])
                    else "full"
                ),
            )
            for item in chunk
        ]
        before = inventory_hashes(self.workspace, self.runner)

        def validate(data: dict[str, Any]) -> None:
            after = inventory_hashes(self.workspace, self.runner)
            changed = sorted(
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            )
            if changed:
                raise SafetyError(
                    "Read-only auditor mutated its isolated repository: "
                    + ", ".join(changed)
                )
            validate_review_evidence(data, self.workspace)
            if data.get("status") == "changes-required" and not data.get("findings"):
                raise ValidationError(
                    "Read-only auditor returned changes-required without evidence."
                )

        instructions = (
            "# Hostile read-only repository audit\n\n"
            "Inspect only the supplied current repository slice. Do not edit any file, "
            "create repository state, run deployment, or propose a finding without exact "
            "file, line-range, and quote evidence. Look for concrete correctness, security, "
            "data-loss, concurrency, compatibility, recovery, misleading-success, intent, "
            "and missing-test defects relevant to the operator's exact request. A finding's "
            "action must be the smallest correct remediation. Use blocking=true for any real "
            "defect that should prevent claiming the repository is correct; this does not "
            "authorize repair. Return approved only when this slice has no supported findings.\n\n"
            f"Audit chunk: {index}/{len(chunks)}\n"
            f"Paths: {chunk_paths}\n\n"
            f"Canonical system map:\n{orchestrator_module._compact_json(system_map)}\n\n"
            f"Human project memory:\n{orchestrator_module._compact_json(memory)}\n\n"
            "Controller-recorded external intelligence:\n"
            f"{orchestrator_module._compact_json(external_intelligence)}"
        )
        return self._call(
            role="reviewer",
            schema="review.schema.json",
            capability_intent=orchestrator_module._capability_intent(brief),
            capability_focus="read-only repository audit " + " ".join(chunk_paths[:20]),
            instructions=instructions,
            context=requests,
            cwd=self.workspace,
            sandbox="read-only",
            metadata={
                "chunk_index": index,
                "chunk_count": len(chunks),
                "audit_only": True,
                "source_mutation_authorized": False,
            },
            call_name=names[offset],
            validator=validate,
        )

    outputs = self._parallel_map(
        chunks,
        audit_chunk,
        enabled=bool(self.config.get("orchestration", {}).get("parallel_review", True)),
    )
    findings: list[dict[str, Any]] = []
    summaries: list[str] = []
    seen: set[tuple[Any, ...]] = set()
    for output in outputs:
        summary = str(output.get("summary") or "").strip()
        if summary:
            summaries.append(summary)
        for finding in output.get("findings", []) or []:
            if not isinstance(finding, dict):
                continue
            identity = (
                str(finding.get("path") or ""),
                int(finding.get("start_line") or 0),
                int(finding.get("end_line") or 0),
                str(finding.get("reason") or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            findings.append(finding)
    findings.sort(
        key=lambda item: (
            str(item.get("path") or ""),
            int(item.get("start_line") or 0),
            str(item.get("id") or ""),
        )
    )
    combined = {
        "status": "changes-required" if findings else "approved",
        "summary": " | ".join(summaries) or "Read-only repository audit completed.",
        "findings": findings,
        "execution_intent": EXECUTION_INTENT_READ_ONLY,
        "source_mutation_authorized": False,
        "chunks_reviewed": len(outputs),
    }
    self.artifacts.write_json("review/review.json", combined)
    return combined


def _diagnostic_gates(self: Any) -> list[dict[str, Any]]:
    gates = list(self._gate_catalog().values())
    if not gates:
        raise GateFailure(
            "Read-only repository analysis requires at least one configured verification gate."
        )
    diagnostic = [replace(gate, required=False) for gate in gates]
    outcomes = self._run_gates(diagnostic, self.workspace)
    for outcome, configured in zip(outcomes, gates, strict=True):
        outcome["configured_required"] = configured.required
    return outcomes


def _run_read_only(
    self: Any,
    *,
    brief_path: Path,
    apply_on_success: bool | None,
    orchestrator_module: Any,
) -> dict[str, Any]:
    if apply_on_success is True:
        raise SafetyError("Read-only repository analysis cannot receive apply authority.")
    completed = self._completed_result()
    if completed is not None:
        return completed
    result: dict[str, Any] = {
        "run_id": self.run_id,
        "status": "BLOCKED",
        "mode": "audit",
        "execution_intent": EXECUTION_INTENT_READ_ONLY,
        "started_at": utc_now(),
        "applied_to_source": False,
    }
    raw_inventory: dict[str, Any] | None = None
    try:
        brief_path = brief_path.expanduser().resolve()
        if not brief_path.is_file():
            raise ValidationError(f"Product brief not found: {brief_path}")
        brief = brief_path.read_text(encoding="utf-8", errors="replace").strip()
        if not brief:
            raise ValidationError("Product brief is empty.")
        self._recover_incomplete_delivery()
        self._validate_required_stack_configuration()

        run_intent = self._artifact_json("intake/run-intent.json")
        if run_intent is None:
            run_intent = orchestrator_module._run_intent_payload(brief, "build", None)
            run_intent["execution_intent"] = EXECUTION_INTENT_READ_ONLY
            run_intent["source_mutation_authorized"] = False
            self.artifacts.write_json("intake/run-intent.json", run_intent, lock=True)

        self._transition(Phase.INTAKE, "Captured exact read-only repository analysis request")
        self._write_or_reuse_text("intake/product-brief.md", brief, lock=True)

        self._transition(Phase.DISCOVERY, "Created isolated read-only repository inventory")
        if self.workspace is None:
            self.workspace = self.mirror.create()
        existing_inventory = self._artifact_json("discovery/inventory.json")
        if isinstance(existing_inventory, dict):
            raw_inventory = existing_inventory
        else:
            raw_inventory = inventory_summary(
                build_inventory(
                    self.workspace,
                    self.runner,
                    float(self.config["context"]["chars_per_token"]),
                    summary_cache_path=self._summary_cache_path(),
                )
            )
            raw_inventory["summary_cache"] = str(self._summary_cache_path())
            self.artifacts.write_json(
                "discovery/inventory.json", raw_inventory, lock=True
            )
        inventory_files = list(raw_inventory.get("files", []))

        obsidian = ObsidianIntegration(
            self.config["integrations"].get("obsidian_vault", ""),
            self.config["integrations"].get("obsidian_export_folder", "MANAGEROO"),
        )
        memory = self._artifact_json("discovery/obsidian-context.json")
        if not isinstance(memory, dict):
            memory = obsidian.search(brief)
            self.artifacts.write_json(
                "discovery/obsidian-context.json", memory, lock=True
            )
        external_intelligence = self._external_intelligence(brief, raw_inventory)

        self._transition(Phase.DECISIONS,"Locked read-only authority; no source edits are permitted")
        self._transition(Phase.REUSE_RESEARCH, "Recorded reusable repository and external intelligence")
        self._transition(Phase.SYSTEM_MAPPING, "Mapping repository for bounded read-only audit")
        system_map = self._map_repository(inventory_files, brief)

        self._transition(Phase.PLAN_COMPILE, "Compiled deterministic read-only audit partitions")
        audit_chunks = ContextCompiler.partition_paths(
            inventory_files,
            max_tokens=_audit_chunk_tokens(self.config),
        ) or [[]]
        audit_plan = {
            "execution_intent": EXECUTION_INTENT_READ_ONLY,
            "source_mutation_authorized": False,
            "chunk_count": len(audit_chunks),
            "chunks": [
                [str(item.get("path") or "") for item in chunk]
                for chunk in audit_chunks
            ],
            "rule": (
                "Review the entire current repository in bounded read-only slices. "
                "Every reported defect must cite exact current source evidence."
            ),
        }
        self._write_or_reuse_json("planning/read-only-contract.json", audit_plan, lock=True)
        self._write_or_reuse_json("planning/audit-plan.json", audit_plan, lock=True)
        self._transition(Phase.PLAN_REVIEW, "Validated read-only audit scope and source invariants")
        self._write_or_reuse_json(
            "planning/plan-review.json",
            {
                "status": "approved",
                "summary": "Every repository slice is read-only; no implementation task exists.",
                "findings": [],
            },
            lock=True,
        )
        self._transition(Phase.CONTRACT_LOCKED, "Read-only analysis contract is immutable")
        self.artifacts.verify_locked()

        self._transition(Phase.IMPLEMENTING, "No implementation authorized; preparing audit evidence")
        self._transition(Phase.VERIFYING, "Running configured gates diagnostically in disposable checkouts")
        gate_results = _diagnostic_gates(self)
        self.artifacts.write_json("verification/gates.json", gate_results)
        self.mirror.assert_source_unchanged()

        self._transition(Phase.REVIEWING, "Launching isolated evidence-bound read-only auditors")
        audit = _read_only_audit(
            self,
            brief=brief,
            inventory=inventory_files,
            system_map=system_map,
            memory=memory,
            external_intelligence=external_intelligence,
            orchestrator_module=orchestrator_module,
        )
        self.mirror.assert_source_unchanged()

        self._transition(Phase.DEMONSTRATING, "Proving the audit completed without source mutation")
        acceptance = [
            {
                "description": "The requested repository analysis completed.",
                "status": "passed",
                "evidence": ["review/review.json"],
            },
            {
                "description": "The product source repository remained unchanged.",
                "status": "passed",
                "evidence": ["verification/source-unchanged.json"],
            },
        ]
        self.artifacts.write_json(
            "verification/source-unchanged.json",
            {
                "status": "passed",
                "execution_intent": EXECUTION_INTENT_READ_ONLY,
                "source_mutation_authorized": False,
            },
            lock=True,
        )
        self.artifacts.write_json(
            "verification/acceptance-evidence.json", acceptance, lock=True
        )
        packet_paths = sorted(
            [
                *self.packet_root.glob("**/prompt.md"),
                *(self.run_root / "review-packets").glob("**/prompt.md"),
            ]
        )
        packet_authority = orchestrator_module._packet_authority_audit(packet_paths)
        if packet_authority["missing"]:
            raise SafetyError(
                "Read-only packet audit found workers missing a request or source-map "
                "authority boundary: "
                + ", ".join(packet_authority["missing"])
            )
        conformance = {
            "status": "passed",
            "execution_intent": EXECUTION_INTENT_READ_ONLY,
            "source_mutation_authorized": False,
            "current_request_was_in_every_worker_packet": (
                packet_authority["source_scoped"] == 0
            ),
            "current_request_was_in_every_request_bound_worker_packet": True,
            "request_bound_worker_packet_count": packet_authority["request_bound"],
            "request_independent_repository_map_packet_count": packet_authority[
                "source_scoped"
            ],
            "worker_packet_count": len(packet_paths),
            "review_status": audit.get("status"),
            "findings_count": len(audit.get("findings", [])),
            "operator_was_not_used_as_an_authorization_gate": True,
        }
        self.artifacts.write_json(
            "verification/intent-conformance.json", conformance, lock=True
        )

        self._transition(Phase.DELIVERING, "Writing durable audit report and zero-byte patch proof")
        patch_path = self.mirror.write_patch(self.run_root / "delivery" / "final.patch")
        if patch_path.stat().st_size != 0:
            raise SafetyError("Read-only repository analysis produced a non-empty source patch.")
        result.update(
            {
                "status": "VERIFIED_PENDING_DELIVERY",
                "product_summary": audit.get("summary", "Read-only repository audit completed."),
                "audit": audit,
                "review": audit,
                "acceptance": acceptance,
                "intent_conformance": conformance,
                "gates": gate_results,
                "files_changed": [],
                "risks": [
                    str(item.get("reason") or "")
                    for item in audit.get("findings", [])
                    if item.get("severity") in {"high", "critical"}
                ],
                "evidence_paths": {
                    "run_root": str(self.run_root),
                    "patch": str(patch_path),
                    "final_report": str(self.run_root / "delivery" / "FINAL-REPORT.md"),
                    "artifact_ledger": str(self.artifacts.ledger_path),
                    "state": str(self.state_path),
                    "audit": str(self.artifacts.root / "review" / "review.json"),
                    "intent_conformance": str(
                        self.artifacts.root / "verification" / "intent-conformance.json"
                    ),
                },
                "finished_at": utc_now(),
            }
        )
        delivery = self.run_root / "delivery"
        pending_report = delivery / "PENDING-REPORT.md"
        pending_result = delivery / "pending-result.json"
        write_report(pending_report, result)
        atomic_write_json(pending_result, result)
        external_capture = self._capture_external_outcome(
            report_path=pending_report,
            result_path=pending_result,
            patch_path=patch_path,
            result=result,
        )
        if external_capture is not None:
            result["external_capture"] = external_capture
            write_report(pending_report, result)
            atomic_write_json(pending_result, result)
        obsidian.export(f"{self.run_id}.md", pending_report.read_text(encoding="utf-8"))
        self.mirror.assert_source_unchanged()

        result["status"] = "COMPLETE"
        result["finished_at"] = utc_now()
        write_report(delivery / "FINAL-REPORT.md", result)
        atomic_write_json(delivery / "final-result.json", result)
        pending_report.unlink(missing_ok=True)
        pending_result.unlink(missing_ok=True)
        self._transition(
            Phase.COMPLETE,
            "Read-only repository analysis and source-invariant proof complete",
        )
        return result
    except Exception as exc:
        if self.state.phase not in {
            Phase.BLOCKED.value,
            Phase.COMPLETE.value,
            Phase.WAITING_FOR_PRODUCT_DECISION.value,
        }:
            try:
                self._transition(Phase.BLOCKED, f"{type(exc).__name__}: {exc}")
            except Exception:
                pass
        result.update(
            {
                "status": self.state.phase,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "finished_at": utc_now(),
                "evidence_paths": {
                    "run_root": str(self.run_root),
                    "state": str(self.state_path),
                    "artifact_ledger": str(self.artifacts.ledger_path),
                },
            }
        )
        delivery = self.run_root / "delivery"
        delivery.mkdir(parents=True, exist_ok=True)
        atomic_write_json(delivery / "failure.json", result)
        atomic_write_json(delivery / "final-result.json", result)
        write_report(delivery / "FINAL-REPORT.md", result)
        raise


def install_read_only_run_policy(
    orchestrator_module: Any, continuity_module: Any
) -> None:
    orchestrator_class = orchestrator_module.Orchestrator
    if getattr(orchestrator_class, "_manageroo_read_only_run_installed", False):
        return
    original_run = orchestrator_class.run

    def run(self: Any, *args: Any, **kwargs: Any):
        brief_value = kwargs.get("brief_path")
        if brief_value is None and args:
            brief_value = args[0]
        if brief_value is not None:
            brief_path = Path(brief_value).expanduser().resolve()
            loaded = _load_request_metadata(brief_path, continuity_module)
            if (
                loaded is not None
                and str(loaded[0].get("execution_intent") or "")
                == EXECUTION_INTENT_READ_ONLY
            ):
                return _run_read_only(
                    self,
                    brief_path=brief_path,
                    apply_on_success=kwargs.get("apply_on_success"),
                    orchestrator_module=orchestrator_module,
                )
        return original_run(self, *args, **kwargs)

    orchestrator_class.run = run
    orchestrator_class._manageroo_read_only_run_installed = True
