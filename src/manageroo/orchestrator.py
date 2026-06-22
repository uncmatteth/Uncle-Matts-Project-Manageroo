from __future__ import annotations

import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from .adapters.base import AgentAdapter, AgentRequest
from .adapters.factory import build_adapter
from .artifacts import ArtifactStore
from .assets import asset_path
from .branding import PROJECT_DIR
from .config import load_config
from .context import ContextCompiler, ContextRequest
from .document_lane import build_document_manifest
from .errors import (
    BlockingDecisionError,
    ContextBudgetError,
    GateFailure,
    SafetyError,
    MANAGEROOError,
    ValidationError,
)
from .gates import Gate, GateRunner, gates_from_config
from .ideas import IdeaInbox
from .integrations import ExternalCommandIntegration, ObsidianIntegration, command_record
from .inventory import build_inventory, inventory_summary
from .jobs import JobStatus, JobStore
from .learning import generate_learning_cards, pending_root, save_pending_learning_cards
from .map_cache import load_system_map_cache, write_system_map_cache
from .policy import CommandPolicy, ScopePolicy
from .report import write_report
from .review import inventory_hashes, validate_review_evidence
from .runner import CommandRunner
from .state import Phase, RunState
from .token_modes import token_mode_prompt
from .util import atomic_write_json, atomic_write_text, new_run_id, read_json, safe_repo_relative, utc_now
from .workspace import WorkspaceMirror

T = TypeVar("T")
R = TypeVar("R")


def _topological_tasks(tasks: list[dict]) -> list[dict]:
    by_id = {task["id"]: task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValidationError("Task IDs must be unique.")
    for task in tasks:
        unknown = set(task.get("dependencies", [])) - set(by_id)
        if unknown:
            raise ValidationError(f"Task {task['id']} has unknown dependencies: {sorted(unknown)}")
    ordered: list[dict] = []
    completed: set[str] = set()
    while len(ordered) < len(tasks):
        ready = [
            task for task in tasks
            if task["id"] not in completed
            and set(task.get("dependencies", [])) <= completed
        ]
        if not ready:
            raise ValidationError("Task dependency graph contains a cycle.")
        for task in sorted(ready, key=lambda item: item["id"]):
            ordered.append(task)
            completed.add(task["id"])
    return ordered


def _compact_json(value: Any, max_chars: int = 180_000) -> str:
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    if len(text) > max_chars:
        raise ValidationError(
            "A planning artifact exceeded the deterministic prompt budget. "
            "The preceding phase must reduce or partition it."
        )
    return text


def _one_line_query(text: str, max_chars: int = 1200) -> str:
    return " ".join(text.split())[:max_chars]


def _artifact_fragment(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_." else "-" for char in value)
    return cleaned.strip("-") or "item"


class Orchestrator:
    def __init__(
        self,
        source_repo: Path,
        *,
        adapter: AgentAdapter | None = None,
        run_id: str | None = None,
        continue_existing: bool = False,
    ):
        self.source_repo = source_repo.resolve()
        self.config = load_config(self.source_repo)
        self.continuing = continue_existing
        if continue_existing and not run_id:
            raise ValidationError("Continuing a run requires a run id.")
        self.run_id = run_id or new_run_id()
        self.run_root = self.source_repo / ".manageroo" / "runs" / self.run_id
        if continue_existing:
            if not self.run_root.is_dir():
                raise ValidationError(f"Run does not exist: {self.run_id}")
        else:
            self.run_root.mkdir(parents=True, exist_ok=False)
        self.logs = self.run_root / "logs"
        self.runner = CommandRunner(self.logs)
        self.adapter = adapter or build_adapter(self.config, self.runner)
        self.state_path = self.run_root / "state.json"
        self.state = RunState.load(self.state_path) if continue_existing else RunState.create(self.run_id)
        if continue_existing and self.state.phase != Phase.COMPLETE.value:
            loaded_phase = self.state.phase
            self.state.reopen_for_continue(f"Continuing durable run from saved phase {loaded_phase}")
            self.state.save(self.state_path)
        elif not continue_existing:
            self.state.save(self.state_path)
        self.artifacts = ArtifactStore(self.run_root / "artifacts")
        self.packet_root = self.run_root / "packets"
        self.output_root = self.run_root / "agent-output"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.job_store = JobStore(self.run_root)
        self.controller_root = self.run_root / "controller"
        self.controller_root.mkdir(parents=True, exist_ok=True)
        self.truth_path = self.controller_root / "truth.json"
        self.phase_journal_path = self.controller_root / "phase-journal.jsonl"
        if not self.truth_path.exists():
            atomic_write_json(
                self.truth_path,
                {
                    "run_id": self.run_id,
                    "source_repo": str(self.source_repo),
                    "stateless_workers": True,
                    "truth": (
                        "Manageroo saves controller truth on disk. Worker agents are "
                        "disposable and receive complete bounded packets."
                    ),
                    "created_at": utc_now(),
                },
            )
        self.mirror = WorkspaceMirror(self.source_repo, self.run_root, self.runner)
        self.workspace: Path | None = self.mirror.load_existing() if continue_existing else None
        self._call_index = self._initial_call_index()
        self._call_lock = threading.Lock()

    def _transition(self, phase: Phase, reason: str) -> None:
        previous = self.state.phase
        if previous != phase.value:
            self.state.transition(phase, reason)
            self.state.save(self.state_path)
        with self.phase_journal_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    {
                        "at": utc_now(),
                        "from": previous,
                        "to": self.state.phase,
                        "reason": reason,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    def _initial_call_index(self) -> int:
        if self.continuing:
            return 0
        highest = 0
        for job in self.job_store.list_jobs():
            prefix = job.id.split("-", 1)[0]
            if prefix.isdigit():
                highest = max(highest, int(prefix))
        return highest

    def _compiler(self, repo: Path | None = None, packet_root: Path | None = None) -> ContextCompiler:
        cfg = self.config["context"]
        return ContextCompiler(
            repo or self.workspace or self.source_repo,
            packet_root or self.packet_root,
            max_input_tokens=int(cfg["max_input_tokens"]),
            reserve_output_tokens=int(cfg["reserve_output_tokens"]),
            chars_per_token=float(cfg["chars_per_token"]),
            max_single_file_tokens=int(cfg["max_single_file_tokens"]),
        )

    def _artifact_json(self, relative: str) -> Any | None:
        path = self.artifacts.root / relative
        if self.continuing and path.is_file():
            return read_json(path)
        return None

    def _artifact_text(self, relative: str) -> str | None:
        path = self.artifacts.root / relative
        if self.continuing and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        return None

    def _write_or_reuse_json(self, relative: str, data: Any, *, lock: bool = False) -> Any:
        existing = self._artifact_json(relative)
        if existing is not None:
            return existing
        self.artifacts.write_json(relative, data, lock=lock)
        return data

    def _write_or_reuse_text(self, relative: str, text: str, *, lock: bool = False) -> str:
        existing = self._artifact_text(relative)
        if existing is not None:
            return existing
        self.artifacts.write_text(relative, text, lock=lock)
        return text

    def _completed_result(self) -> dict[str, Any] | None:
        if not self.continuing or self.state.phase != Phase.COMPLETE.value:
            return None
        path = self.run_root / "delivery" / "final-result.json"
        if path.is_file():
            data = read_json(path)
            if isinstance(data, dict):
                return data
        return None

    def _next_call_name(self, role: str) -> str:
        with self._call_lock:
            self._call_index += 1
            return f"{self._call_index:03d}-{role}"

    def _max_parallel_agent_calls(self) -> int:
        value = self.config.get("orchestration", {}).get("max_parallel_agent_calls", 1)
        return max(1, int(value))

    def _summary_cache_path(self) -> Path:
        path = self.source_repo / PROJECT_DIR / "cache" / "file-summaries.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _system_map_cache_path(self) -> Path:
        path = self.source_repo / PROJECT_DIR / "cache" / "system-map.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _parallel_map(
        self,
        items: list[T],
        worker: Callable[[int, T], R],
        *,
        enabled: bool,
    ) -> list[R]:
        if not enabled or len(items) <= 1 or self._max_parallel_agent_calls() <= 1:
            return [worker(index, item) for index, item in enumerate(items)]
        results: list[R | None] = [None] * len(items)
        with ThreadPoolExecutor(max_workers=min(len(items), self._max_parallel_agent_calls())) as pool:
            futures = {
                pool.submit(worker, index, item): index
                for index, item in enumerate(items)
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return [item for item in results if item is not None]

    def _call(
        self,
        *,
        role: str,
        schema: str,
        instructions: str,
        context: Iterable[ContextRequest] = (),
        sandbox: str = "read-only",
        metadata: dict | None = None,
        cwd: Path | None = None,
        packet_root: Path | None = None,
        call_name: str | None = None,
        validator: Callable[[dict], None] | None = None,
    ) -> dict:
        name = call_name or self._next_call_name(role)
        repo = cwd or self.workspace
        if repo is None:
            raise RuntimeError("Workspace has not been created.")
        context_requests = list(context)
        token_prompt = token_mode_prompt()
        if token_prompt:
            instructions = token_prompt + "\n\n" + instructions
        metadata = metadata or {}
        allowed_paths = metadata.get("task", {}).get("allowed_paths", [])
        job = self.job_store.create_or_load_job(
            name,
            role=role,
            schema=schema,
            instructions=instructions,
            context=context_requests,
            allowed_paths=allowed_paths,
            dependencies=metadata.get("dependencies", []),
            metadata=metadata,
            sandbox=sandbox,
        )
        if job.status == JobStatus.COMPLETE.value:
            completed = self.job_store.completed_data(name, self.artifacts.root)
            if completed is not None:
                return completed

        max_attempts = max(1, int(self.config.get("orchestration", {}).get("max_worker_attempts", 2)))
        attempt_limit = len(self.job_store.attempts_for(name)) + max_attempts
        last_error: Exception | None = None
        while len(self.job_store.attempts_for(name)) < attempt_limit:
            attempt = self.job_store.begin_attempt(name)
            try:
                attempt_packet_root = packet_root or (self.packet_root / name)
                compiler = self._compiler(repo=repo, packet_root=attempt_packet_root)
                packet = compiler.compile(
                    attempt.attempt_id,
                    instructions=instructions,
                    requests=context_requests,
                    metadata={"role": role, "job_id": name, "attempt_id": attempt.attempt_id, **metadata},
                )
                self.job_store.record_packet(name, attempt.attempt_id, packet_path=packet)
                output = self.output_root / name / f"{attempt.attempt_id}.json"
                compiler.validate_freshness(read_json(packet / "manifest.json"))
                request = AgentRequest(
                    role=role,
                    prompt_path=packet / "prompt.md",
                    schema_path=asset_path(f"schemas/{schema}"),
                    output_path=output,
                    cwd=repo,
                    sandbox=sandbox,
                    timeout_seconds=int(self.config["agent"]["timeout_seconds"]),
                    metadata=metadata,
                )
                response = self.adapter.run(request)
                if validator is not None:
                    validator(response.data)
                artifact_relative = f"agent/{name}.json"
                artifact = self.artifacts.write_json(artifact_relative, response.data)
                self.job_store.complete_attempt(
                    name,
                    attempt.attempt_id,
                    output_path=output,
                    data=response.data,
                    command=response.command,
                    stdout=response.stdout,
                    stderr=response.stderr,
                )
                self.job_store.complete_job(
                    name,
                    output_artifact=artifact_relative,
                    data=response.data,
                    artifact_path=self.artifacts.root / artifact.path,
                )
                return response.data
            except ContextBudgetError as exc:
                self.job_store.fail_attempt(name, attempt.attempt_id, exc)
                self.job_store.block_job(name, exc)
                raise
            except Exception as exc:
                last_error = exc
                self.job_store.fail_attempt(name, attempt.attempt_id, exc)
                if len(self.job_store.attempts_for(name)) >= max_attempts:
                    self.job_store.fail_job(name, exc)
                    raise
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Worker job did not run: {name}")

    def _documentation_context(self, inventory: list[dict]) -> list[ContextRequest]:
        preferred = []
        priority_names = {
            "AGENTS.md": 100,
            "CONTEXT.md": 98,
            "ARCHITECTURE.md": 95,
            "README.md": 90,
            "CLAUDE.md": 85,
            "CONTRIBUTING.md": 80,
        }
        for item in inventory:
            path = item["path"]
            name = Path(path).name
            if name in priority_names or path.startswith("docs/"):
                preferred.append(
                    ContextRequest(
                        path=path,
                        reason="Repository-owned product, architecture, or operating guidance.",
                        required=False,
                        priority=priority_names.get(name, 60),
                        mode=(
                            "summary"
                            if item.get("content_kind") == "media"
                            or int(item.get("estimated_tokens", 0))
                            > int(self.config["context"]["max_single_file_tokens"])
                            else "full"
                        ),
                    )
                )
        return preferred[:30]

    def _resolve_decisions(self, product: dict) -> tuple[dict, list[dict]]:
        unresolved: list[dict] = []
        resolved = json.loads(json.dumps(product))
        for decision in resolved.get("blocking_decisions", []):
            if decision.get("chosen"):
                continue
            recommended = decision.get("recommended")
            reversible = bool(decision.get("reversible"))
            category = decision.get("category", "product")
            if reversible and recommended:
                decision["chosen"] = recommended
                decision["resolution_source"] = "MANAGEROO reversible-default policy"
            elif category in {"cosmetic", "implementation"} and recommended:
                decision["chosen"] = recommended
                decision["resolution_source"] = "MANAGEROO conventional-default policy"
            else:
                unresolved.append(decision)
        return resolved, unresolved

    def _gate_catalog(self) -> dict[str, Gate]:
        gates = gates_from_config(self.config)
        return {gate.id: gate for gate in gates}

    def _plan_context_preflight(self, plan: dict, inventory: list[dict]) -> list[dict]:
        by_path = {item["path"]: item for item in inventory}
        usable = (
            int(self.config["context"]["max_input_tokens"])
            - int(self.config["context"]["reserve_output_tokens"])
        )
        max_single = int(self.config["context"]["max_single_file_tokens"])
        findings: list[dict] = []
        for task in plan.get("tasks", []):
            total = 0
            for path in task.get("context_paths", []):
                item = by_path.get(path)
                if item is None:
                    findings.append({
                        "id": f"CTX-MISSING-{task['id']}-{len(findings)+1}",
                        "severity": "high",
                        "problem": f"Task {task['id']} requires missing context path {path}.",
                        "required_change": "Correct the path or remove it from required task context.",
                    })
                    continue
                tokens = int(item.get("estimated_tokens", 0))
                total += tokens
                if tokens > max_single:
                    findings.append({
                        "id": f"CTX-FILE-{task['id']}-{len(findings)+1}",
                        "severity": "high",
                        "problem": (
                            f"Task {task['id']} requires {path} at approximately {tokens} tokens, "
                            f"above the single-slice limit {max_single}."
                        ),
                        "required_change": (
                            "Split the task or provide a narrower architectural boundary so the "
                            "controller can compile bounded line ranges."
                        ),
                    })
            if total > usable:
                findings.append({
                    "id": f"CTX-TOTAL-{task['id']}",
                    "severity": "high",
                    "problem": (
                        f"Task {task['id']} requires approximately {total} context tokens, "
                        f"above the usable budget {usable}."
                    ),
                    "required_change": "Decompose the task at a stable interface before implementation.",
                })
        return findings

    def _gates_for_ids(self, ids: list[str]) -> list[Gate]:
        catalog = self._gate_catalog()
        unknown = sorted(set(ids) - set(catalog))
        if unknown:
            raise ValidationError(
                "Plan referenced unknown command gates. Agents may not invent executable commands: "
                + ", ".join(unknown)
            )
        return [catalog[item] for item in ids]

    def _run_gates(self, gates: list[Gate], workspace: Path) -> list[dict]:
        policy = CommandPolicy(tuple(self.config["safety"]["allowed_programs"]))
        gate_runner = GateRunner(self.runner, policy, self.logs)
        return [item.to_dict() for item in gate_runner.run(gates, workspace)]

    def _external_values(self, *, brief: str) -> dict[str, str]:
        assert self.workspace is not None
        return {
            "repo": str(self.source_repo),
            "workspace": str(self.workspace),
            "run_root": str(self.run_root),
            "query": _one_line_query(brief),
            "brief_file": str(self.artifacts.root / "intake" / "product-brief.md"),
            "inventory_file": str(self.artifacts.root / "discovery" / "inventory.json"),
            "obsidian_context_file": str(self.artifacts.root / "discovery" / "obsidian-context.json"),
            "external_context_file": str(self.artifacts.root / "discovery" / "external-intelligence.json"),
            "document_manifest_file": str(self.artifacts.root / "discovery" / "document-manifest.json"),
            "document_intelligence_file": str(self.artifacts.root / "discovery" / "document-intelligence.json"),
            "document_state_dir": str(self.artifacts.root / "discovery" / "document-state"),
        }

    def _run_optional_external_command(
        self,
        *,
        name: str,
        argv_template: list[str],
        values: dict[str, str],
        cwd: Path,
        timeout_seconds: int = 180,
    ) -> dict:
        if not argv_template:
            return {"name": name, "enabled": False, "ok": False}
        try:
            result = ExternalCommandIntegration(argv_template, self.runner).run(
                cwd=cwd,
                values=values,
                timeout_seconds=timeout_seconds,
                log_name=f"external-{name}",
            )
            return command_record(name, result)
        except Exception as exc:
            return {
                "name": name,
                "enabled": True,
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    def _document_intelligence(self, *, brief: str, inventory: dict[str, Any]) -> dict:
        existing = self._artifact_json("discovery/document-intelligence.json")
        if existing is not None:
            return existing
        cfg = self.config.get("integrations", {})
        manifest = build_document_manifest(
            inventory,
            max_single_file_tokens=int(self.config["context"]["max_single_file_tokens"]),
        )
        manifest = self._write_or_reuse_json("discovery/document-manifest.json", manifest, lock=True)

        values = self._external_values(brief=brief)
        document_state_dir = self.artifacts.root / "discovery" / "document-state"
        document_state_dir.mkdir(parents=True, exist_ok=True)
        values.update(
            {
                "document_manifest_file": str(self.artifacts.root / "discovery" / "document-manifest.json"),
                "document_intelligence_file": str(self.artifacts.root / "discovery" / "document-intelligence.json"),
                "document_state_dir": str(document_state_dir),
            }
        )

        record = self._run_optional_external_command(
            name="document-analysis",
            argv_template=list(cfg.get("document_analysis_command", []) or []),
            values=values,
            cwd=self.run_root,
            timeout_seconds=600,
        )
        records = [record] if record.get("enabled") else []
        skipped_reason = ""
        if not record.get("enabled"):
            skipped_reason = (
                "No document/prose files were detected."
                if int(manifest["summary"]["document_files"]) == 0
                else "document_analysis_command is empty."
            )
        payload = {
            "summary": {
                **manifest["summary"],
                "enabled": [item["name"] for item in records if item.get("enabled")],
                "passed": [item["name"] for item in records if item.get("ok")],
                "failed_optional": [
                    item["name"]
                    for item in records
                    if item.get("enabled") and not item.get("ok")
                ],
                "skipped_reason": skipped_reason,
            },
            "records": records,
            "manifest_file": str(self.artifacts.root / "discovery" / "document-manifest.json"),
            "note": (
                "Document/prose analysis is an optional command-owned evidence lane. "
                "Passing output may inform planning. Failure is recorded as optional context, "
                "not handed to the AI as a freehand long-document repair prompt."
            ),
        }
        self.artifacts.write_json("discovery/document-intelligence.json", payload, lock=True)
        return payload

    def _external_intelligence(self, brief: str, inventory: dict[str, Any]) -> dict:
        existing = self._artifact_json("discovery/external-intelligence.json")
        if existing is not None:
            return existing
        cfg = self.config.get("integrations", {})
        values = self._external_values(brief=brief)
        document_intelligence = self._document_intelligence(brief=brief, inventory=inventory)
        commands = [
            ("gbrain-search", cfg.get("gbrain_search_command", [])),
            ("gitnexus-analyze", cfg.get("gitnexus_analyze_command", [])),
            ("gitnexus-query", cfg.get("gitnexus_query_command", [])),
        ]
        records = list(document_intelligence.get("records", []))
        records.extend(
            self._run_optional_external_command(
                name=name,
                argv_template=list(argv_template or []),
                values=values,
                cwd=self.source_repo,
            )
            for name, argv_template in commands
        )
        summary = {
            "enabled": [item["name"] for item in records if item.get("enabled")],
            "passed": [item["name"] for item in records if item.get("ok")],
            "failed_optional": [
                item["name"]
                for item in records
                if item.get("enabled") and not item.get("ok")
            ],
        }
        payload = {
            "summary": summary,
            "records": records,
            "document_intelligence": document_intelligence,
            "note": (
                "These tools are optional context. Passing output may inform planning; "
                "failed or missing tools do not block the core controller run."
            ),
        }
        self.artifacts.write_json("discovery/external-intelligence.json", payload, lock=True)
        return payload

    def _external_review_repair_commands(self) -> list[tuple[str, list[str]]]:
        cfg = self.config.get("integrations", {})
        return [
            ("autoreview", list(cfg.get("autoreview_command", []) or [])),
            ("clawpatch", list(cfg.get("clawpatch_command", []) or [])),
        ]

    def _run_external_review_repair_lanes(
        self,
        *,
        brief: str,
        plan: dict,
        gate_results: list[dict],
    ) -> dict | None:
        assert self.workspace is not None
        commands = [
            (name, argv_template)
            for name, argv_template in self._external_review_repair_commands()
            if argv_template
        ]
        if not commands:
            return None

        allowed_paths = sorted(
            {
                safe_repo_relative(path)
                for task in plan.get("tasks", [])
                for path in task.get("allowed_paths", [])
            }
        )
        input_payload = {
            "rule": (
                "AUTOREVIEW and Clawpatch are command-owned repair lanes. "
                "The controller must not freehand fixes from their findings."
            ),
            "allowed_paths": allowed_paths,
            "gate_results": gate_results,
            "task_plan_file": str(self.artifacts.root / "planning" / "task-plan.json"),
            "gates_file": str(self.artifacts.root / "verification" / "gates.json"),
        }
        self.artifacts.write_json("review/external-review-repair-input.json", input_payload)
        values = self._external_values(brief=brief)
        values.update(
            {
                "repo": str(self.workspace),
                "workspace": str(self.workspace),
                "source_repo": str(self.source_repo),
                "external_state_dir": str(self.artifacts.root / "review" / "external-state"),
                "task_plan_file": str(self.artifacts.root / "planning" / "task-plan.json"),
                "gates_file": str(self.artifacts.root / "verification" / "gates.json"),
                "external_review_repair_input_file": str(
                    self.artifacts.root / "review" / "external-review-repair-input.json"
                ),
            }
        )
        (self.artifacts.root / "review" / "external-state").mkdir(parents=True, exist_ok=True)

        before_all = self.mirror.head()
        records: list[dict] = []
        failed: list[str] = []
        for name, argv_template in commands:
            before_command = self.mirror.head()
            record = self._run_optional_external_command(
                name=name,
                argv_template=argv_template,
                values=values,
                cwd=self.workspace,
                timeout_seconds=600,
            )
            changed_paths = self.mirror.changed_paths(before_command)
            record.update(
                {
                    "command_owned_repair_lane": True,
                    "ai_freehand_repair_allowed": False,
                    "changed_paths": changed_paths,
                }
            )
            policy_error = ""
            if self.mirror.head() != before_command:
                policy_error = "External review/repair lane changed Git HEAD; the controller owns checkpoints."
            try:
                ScopePolicy(tuple(allowed_paths)).validate_paths(changed_paths)
            except SafetyError as exc:
                policy_error = str(exc)
            if policy_error:
                record["ok"] = False
                record["policy_error"] = policy_error
            if record.get("ok") and changed_paths:
                record["checkpoint"] = self.mirror.checkpoint(
                    f"MANAGEROO command-owned {name} repair lane"
                )
            if not record.get("ok"):
                failed.append(name)
            records.append(record)

        changed_total = self.mirror.changed_paths(before_all)
        payload = {
            "summary": {
                "enabled": [name for name, _ in commands],
                "passed": [item["name"] for item in records if item.get("ok")],
                "failed": failed,
                "changed_paths": changed_total,
                "command_owned_repair_lanes": True,
                "ai_freehand_repair_allowed": False,
            },
            "records": records,
            "note": (
                "AUTOREVIEW and Clawpatch findings are not fed to the AI repairer. "
                "These configured commands own their review/repair lane; a nonzero exit, timeout, "
                "or policy error blocks the run with captured evidence."
            ),
        }
        self.artifacts.write_json("review/external-review-repair.json", payload)
        if failed:
            raise ValidationError(
                "Configured external review/repair lane failed: "
                + ", ".join(failed)
                + ". See review/external-review-repair.json. "
                "The AI repairer was not asked to fix AUTOREVIEW or Clawpatch findings."
            )
        return payload

    def _capture_external_outcome(
        self,
        *,
        report_path: Path,
        result_path: Path,
        patch_path: Path,
        result: dict,
    ) -> dict | None:
        cfg = self.config.get("integrations", {})
        argv_template = list(cfg.get("gbrain_capture_command", []) or [])
        if not argv_template:
            return None
        values = {
            "repo": str(self.source_repo),
            "run_root": str(self.run_root),
            "report_file": str(report_path),
            "result_file": str(result_path),
            "patch_file": str(patch_path),
            "status": str(result.get("status", "")),
            "summary": str(result.get("product_summary", "")),
            "files_changed": ",".join(result.get("files_changed", [])),
        }
        record = self._run_optional_external_command(
            name="gbrain-capture",
            argv_template=argv_template,
            values=values,
            cwd=self.source_repo,
        )
        payload = {
            "summary": {
                "enabled": True,
                "passed": bool(record.get("ok")),
                "failed_optional": [] if record.get("ok") else ["gbrain-capture"],
            },
            "records": [record],
        }
        self.artifacts.write_json("delivery/external-capture.json", payload)
        return payload

    def _record_learning(
        self,
        *,
        result: dict[str, Any],
        inventory: dict[str, Any] | None,
        external_intelligence: dict[str, Any] | None,
        external_review_repair: dict[str, Any] | None,
    ) -> dict[str, Any]:
        cards = generate_learning_cards(
            repo=self.source_repo,
            result=result,
            inventory=inventory,
            external_intelligence=external_intelligence,
            external_review_repair=external_review_repair,
        )
        saved = save_pending_learning_cards(self.source_repo, cards)
        artifact_path = self.artifacts.root / "learning" / "improvement-cards.json"
        self.artifacts.write_json(
            "learning/improvement-cards.json",
            {
                "schema_version": 1,
                "cards": cards,
                "saved_pending": saved,
                "pending_dir": str(pending_root(self.source_repo)),
                "approval_gated": True,
                "note": (
                    "Learning cards are suggestions. MANAGEROO may save pending cards, "
                    "but behavior, skills, config, docs, and memory changes require explicit apply approval."
                ),
            },
        )
        return {
            "cards": len(cards),
            "pending_saved": len(saved),
            "artifact": str(artifact_path),
            "pending_dir": str(pending_root(self.source_repo)),
            "approval_gated": True,
        }

    def _map_repository(self, inventory: list[dict], brief: str) -> dict:
        existing = self._artifact_json("planning/system-map.json")
        if existing is not None:
            return existing
        cache_path = self._system_map_cache_path()
        cached = load_system_map_cache(cache_path, inventory=inventory, brief=brief)
        if cached is not None:
            self._write_or_reuse_json("planning/system-map.json", cached, lock=True)
            self._write_or_reuse_json(
                "planning/system-map-cache.json",
                {"status": "hit", "path": str(cache_path)},
                lock=True,
            )
            return cached

        cfg = self.config["context"]
        chunks = ContextCompiler.partition_paths(
            inventory, max_tokens=int(cfg["map_chunk_tokens"])
        )
        names = [self._next_call_name("repository-mapper") for _ in chunks]

        def map_chunk(offset: int, chunk: list[dict]) -> dict:
            index = offset + 1
            requests = [
                ContextRequest(
                    path=item["path"],
                    reason=f"Repository mapping chunk {index}; identify responsibility and relationships.",
                    required=False,
                    priority=50,
                    mode=(
                        "summary"
                        if item.get("content_kind") == "media"
                        or int(item.get("estimated_tokens", 0))
                        > int(cfg["max_single_file_tokens"])
                        else "full"
                    ),
                )
                for item in chunk
            ]
            chunk_metadata = [
                {
                    "path": item["path"],
                    "language": item.get("language", ""),
                    "content_kind": item.get("content_kind", ""),
                    "bytes": item.get("bytes", 0),
                    "line_count": item.get("line_count", 0),
                    "estimated_tokens": item.get("estimated_tokens", 0),
                    "summary": item.get("summary", ""),
                }
                for item in chunk
            ]
            return self._call(
                role="repository-mapper",
                schema="repository-map-part.schema.json",
                instructions=(
                    "# Repository mapping role\n\n"
                    "Map only the supplied repository slice. Identify modules, interfaces, "
                    "data flows, trust boundaries, and risks. Do not propose edits. "
                    "Do not assume omitted files are absent from the product. Media and oversized "
                    "prose may appear as generated summaries; treat those summaries as metadata, "
                    "not full OCR or vision interpretation.\n\n"
                    f"Product brief:\n{brief}\n\n"
                    f"Chunk ID: chunk-{index}\n"
                    f"Files assigned: {[item['path'] for item in chunk]}\n\n"
                    f"Assigned file metadata:\n{_compact_json(chunk_metadata)}"
                ),
                context=requests,
                metadata={"chunk_id": f"chunk-{index}", "paths": [item["path"] for item in chunk]},
                call_name=names[offset],
            )

        maps = self._parallel_map(
            chunks,
            map_chunk,
            enabled=bool(self.config.get("orchestration", {}).get("parallel_mapping", True)),
        )

        reduced = self._call(
            role="map-reducer",
            schema="system-map.schema.json",
            instructions=(
                "# Repository map reducer\n\n"
                "Combine the independently produced map parts into one canonical system map. "
                "Resolve duplicates and contradictions conservatively. Preserve uncertainty. "
                "Return integration order at the capability level, not implementation details.\n\n"
                f"Product brief:\n{brief}\n\n"
                f"Map parts:\n{_compact_json(maps)}"
            ),
            metadata={"all_paths": [item["path"] for item in inventory]},
        )
        self._write_or_reuse_json("planning/system-map.json", reduced, lock=True)
        write_system_map_cache(cache_path, inventory=inventory, brief=brief, system_map=reduced)
        self._write_or_reuse_json(
            "planning/system-map-cache.json",
            {"status": "miss", "path": str(cache_path)},
            lock=True,
        )
        return reduced

    def _perform_review(
        self,
        plan: dict,
        product: dict,
        gates: list[dict],
        changed_paths: list[str],
    ) -> dict:
        assert self.workspace is not None
        review_repo = self.mirror.clone_for_review(self.run_root / "review-workspace")
        review_packet_root = self.run_root / "review-packets"
        review_packet_root.mkdir(parents=True, exist_ok=True)
        review_outputs: list[dict] = []

        inventory = [
            asdict(item)
            for item in build_inventory(
                review_repo, self.runner, float(self.config["context"]["chars_per_token"])
            )
            if item.path in changed_paths
        ]
        review_chunk_tokens = max(
            2000,
            min(
                int(self.config["context"]["map_chunk_tokens"]) // 2,
                (
                    int(self.config["context"]["max_input_tokens"])
                    - int(self.config["context"]["reserve_output_tokens"])
                ) // 3,
            ),
        )
        chunks = ContextCompiler.partition_paths(
            inventory,
            max_tokens=review_chunk_tokens,
        ) or [[]]
        names = [self._next_call_name(f"reviewer-{index}") for index in range(1, len(chunks) + 1)]

        def review_chunk(offset: int, chunk: list[dict]) -> dict:
            index = offset + 1
            context = [
                ContextRequest(
                    path=item["path"],
                    reason="Changed implementation under independent review.",
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
            chunk_paths = [item["path"] for item in chunk]
            diff_result = self.runner.run(
                ["git", "diff", "--no-ext-diff", self.mirror.baseline_commit, "HEAD", "--", *chunk_paths],
                cwd=review_repo,
                timeout_seconds=120,
            )
            if not diff_result.passed:
                raise SafetyError("Could not construct reviewer diff: " + diff_result.stderr)
            instructions = (
                "# Independent evidence review\n\n"
                "You did not author this patch. Review only against the locked product model, "
                "task plan, and deterministic evidence below. Report concrete correctness, "
                "security, data-loss, concurrency, compatibility, and missing-test defects. "
                "Do not mutate any file. Every blocking finding must cite an exact current file, "
                "valid line range, and matching quote.\n\n"
                f"Product model:\n{_compact_json(product)}\n\n"
                f"Task plan:\n{_compact_json(plan)}\n\n"
                f"Gate evidence:\n{_compact_json(gates)}\n\n"
                f"Review chunk {index}/{len(chunks)} paths: {chunk_paths}\n\n"
                f"Patch diff for this chunk:\n```diff\n{diff_result.stdout}\n```"
            )
            token_prompt = token_mode_prompt()
            if token_prompt:
                instructions = token_prompt + "\n\n" + instructions
            name = names[offset]
            before = inventory_hashes(review_repo, self.runner)

            def validate_review_worker(data: dict) -> None:
                after = inventory_hashes(review_repo, self.runner)
                if before != after:
                    changed = sorted(set(before) | set(after))
                    changed = [item for item in changed if before.get(item) != after.get(item)]
                    raise SafetyError("Reviewer mutated its isolated repository: " + ", ".join(changed))
                validate_review_evidence(data, review_repo)

            return self._call(
                role="reviewer",
                schema="review.schema.json",
                instructions=instructions,
                context=context,
                cwd=review_repo,
                sandbox="read-only",
                packet_root=review_packet_root / name,
                metadata={"chunk_index": index, "chunk_count": len(chunks)},
                call_name=name,
                validator=validate_review_worker,
            )

        review_outputs = self._parallel_map(
            chunks,
            review_chunk,
            enabled=bool(self.config.get("orchestration", {}).get("parallel_review", True)),
        )

        findings = []
        statuses = []
        summaries = []
        for review in review_outputs:
            findings.extend(review.get("findings", []))
            statuses.append(review.get("status"))
            summaries.append(review.get("summary", ""))
        combined = {
            "status": "changes-required"
            if any(item.get("blocking") for item in findings)
            else "approved",
            "summary": " | ".join(item for item in summaries if item),
            "findings": findings,
        }
        self.artifacts.write_json("review/review.json", combined)
        return combined

    def run(
        self,
        *,
        brief_path: Path,
        mode: str,
        apply_on_success: bool | None = None,
    ) -> dict:
        result: dict[str, Any] = {
            "run_id": self.run_id,
            "status": "BLOCKED",
            "mode": mode,
            "started_at": utc_now(),
        }
        raw_inventory: dict[str, Any] | None = None
        external_intelligence: dict[str, Any] | None = None
        external_review_repair: dict[str, Any] | None = None
        try:
            completed = self._completed_result()
            if completed is not None:
                return completed
            if mode not in {"build", "repair"}:
                raise ValidationError("Mode must be 'build' or 'repair'.")
            brief_path = brief_path.resolve()
            if not brief_path.is_file():
                raise ValidationError(f"Product brief not found: {brief_path}")
            brief = brief_path.read_text(encoding="utf-8", errors="replace").strip()
            if not brief:
                raise ValidationError("Product brief is empty.")

            self._transition(Phase.INTAKE, "Captured product request and pending ideas")
            self._write_or_reuse_text("intake/product-brief.md", brief, lock=True)
            pending_ideas = self._artifact_json("intake/pending-ideas.json")
            if pending_ideas is None:
                pending_ideas = IdeaInbox(self.source_repo).attach_pending(self.run_id)
                self.artifacts.write_json("intake/pending-ideas.json", pending_ideas, lock=True)

            self._transition(Phase.DISCOVERY, "Created isolated source mirror and inventory")
            if self.workspace is None:
                self.workspace = self.mirror.create()
            existing_inventory = self._artifact_json("discovery/inventory.json")
            if existing_inventory is not None:
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
                self.artifacts.write_json("discovery/inventory.json", raw_inventory, lock=True)
            inventory_files = raw_inventory["files"]

            obsidian = ObsidianIntegration(
                self.config["integrations"].get("obsidian_vault", ""),
                self.config["integrations"].get("obsidian_export_folder", "MANAGEROO"),
            )
            memory = self._artifact_json("discovery/obsidian-context.json")
            if memory is None:
                memory = obsidian.search(brief)
                self.artifacts.write_json("discovery/obsidian-context.json", memory, lock=True)
            external_intelligence = self._external_intelligence(brief, raw_inventory)

            product = self._artifact_json("planning/product-model.json")
            unresolved: list[dict] = []
            if product is None:
                product = self._call(
                    role="product-analyst",
                    schema="product-model.schema.json",
                    instructions=(
                        "# Product analysis role\n\n"
                        "Convert the operator's normal-language brief into a complete product model. "
                        "The operator is the product authority but is not expected to review code. "
                        "Infer conventional, reversible details. Raise a blocking decision only when "
                        "guessing could cause irreversible data loss, legal exposure, meaningful cost, "
                        "security boundary changes, or a materially different product. "
                        "Do not write implementation code.\n\n"
                        f"Mode: {mode}\n\n"
                        f"Product brief:\n{brief}\n\n"
                        f"Captured evolving ideas:\n{_compact_json(pending_ideas)}\n\n"
                        f"Relevant human notes:\n{_compact_json(memory)}\n\n"
                        f"External repo intelligence:\n{_compact_json(external_intelligence)}\n\n"
                        f"Repository summary:\n{_compact_json({k: v for k, v in raw_inventory.items() if k != 'files'})}"
                    ),
                    context=self._documentation_context(inventory_files),
                )
                product, unresolved = self._resolve_decisions(product)
                self.artifacts.write_json("planning/product-model.json", product, lock=not unresolved)
            self._transition(Phase.DECISIONS, "Applied deterministic reversible-decision policy")
            if unresolved:
                self.artifacts.write_json("planning/blocking-decisions.json", {"decisions": unresolved}, lock=True)
                self._transition(
                    Phase.WAITING_FOR_PRODUCT_DECISION,
                    "Irreversible or high-impact product decisions require the operator",
                )
                raise BlockingDecisionError(
                    "The run requires product decisions. See planning/blocking-decisions.json."
                )

            self._transition(Phase.REUSE_RESEARCH, "Evaluating reuse before custom implementation")
            reuse = self._artifact_json("planning/reuse-report.json")
            if reuse is None:
                reuse = self._call(
                    role="reuse-researcher",
                    schema="reuse-report.schema.json",
                    instructions=(
                        "# Reuse-first research role\n\n"
                        "Before custom code is authorized, inspect the repository and identify existing "
                        "internal capabilities, platform-native functions, and maintained dependencies "
                        "that can satisfy each need. Prefer repository-owned and already-approved "
                        "components. Record license uncertainty rather than inventing facts. "
                        "Do not install anything and do not edit the repository.\n\n"
                        f"Product model:\n{_compact_json(product)}\n\n"
                        f"External repo intelligence:\n{_compact_json(external_intelligence)}\n\n"
                        f"Repository summary:\n{_compact_json({k: v for k, v in raw_inventory.items() if k != 'files'})}"
                    ),
                    context=self._documentation_context(inventory_files),
                )
                self.artifacts.write_json("planning/reuse-report.json", reuse, lock=True)

            self._transition(Phase.SYSTEM_MAPPING, "Mapping repository through bounded map/reduce packets")
            system_map = self._map_repository(inventory_files, brief)

            self._transition(Phase.PLAN_COMPILE, "Compiling complete dependency-ordered task graph")
            plan = self._artifact_json("planning/task-plan.json")
            plan_review = self._artifact_json("planning/plan-review.json")
            if plan is None or plan_review is None:
                gate_ids = list(self._gate_catalog())
                plan = self._call(
                    role="plan-compiler",
                    schema="task-plan.schema.json",
                    instructions=(
                        "# Plan compiler role\n\n"
                        "Compile the entire requested change before implementation. Produce bounded, "
                        "dependency-ordered tasks with exact allowed paths, context paths, acceptance "
                        "criteria, and references only to the provided deterministic gate IDs. "
                        "Do not invent shell commands. Prefer sequential correctness over speculative "
                        "parallelism. Every interface shared by tasks must be explicit. "
                        "No implementation may begin until this plan survives review.\n\n"
                        f"Product model:\n{_compact_json(product)}\n\n"
                        f"Reuse report:\n{_compact_json(reuse)}\n\n"
                        f"System map:\n{_compact_json(system_map)}\n\n"
                        f"External repo intelligence:\n{_compact_json(external_intelligence)}\n\n"
                        f"Available gate IDs: {gate_ids}"
                    ),
                    metadata={
                        "gate_ids": gate_ids,
                        "fixture_target": "manageroo_fixture.txt",
                    },
                )

                max_cycles = int(self.config["project"]["max_plan_review_cycles"])
                while True:
                    deterministic_plan_findings = self._plan_context_preflight(plan, inventory_files)
                    self._transition(Phase.PLAN_REVIEW, "Independent plan review")
                    plan_review = self._call(
                        role="plan-reviewer",
                        schema="plan-review.schema.json",
                        instructions=(
                            "# Adversarial plan review\n\n"
                            "Review the complete plan before code exists. Look for missing product "
                            "capabilities, incompatible interfaces, dependency cycles, untestable "
                            "acceptance criteria, excessive scope, unsafe migrations, and context packets "
                            "that are too broad. Do not rewrite the plan; report exact findings.\n\n"
                            f"Product model:\n{_compact_json(product)}\n\n"
                            f"Reuse report:\n{_compact_json(reuse)}\n\n"
                            f"System map:\n{_compact_json(system_map)}\n\n"
                            f"Proposed plan:\n{_compact_json(plan)}\n\n"
                            f"Deterministic context preflight findings:\n"
                            f"{_compact_json(deterministic_plan_findings)}"
                        ),
                    )
                    if deterministic_plan_findings:
                        plan_review = {
                            "status": "changes-required",
                            "summary": (
                                plan_review.get("summary", "")
                                + " Controller context preflight requires plan decomposition."
                            ).strip(),
                            "findings": plan_review.get("findings", [])
                            + deterministic_plan_findings,
                        }
                    if plan_review["status"] == "approved":
                        break
                    self.state.plan_review_cycles += 1
                    self.state.save(self.state_path)
                    if self.state.plan_review_cycles >= max_cycles:
                        raise ValidationError("Plan review did not converge within the configured limit.")
                    self._transition(Phase.PLAN_COMPILE, "Repairing plan-review findings")
                    plan = self._call(
                        role="plan-compiler",
                        schema="task-plan.schema.json",
                        instructions=(
                            "# Plan repair\n\n"
                            "Repair the proposed plan using the verified review findings. Preserve the "
                            "product model and system boundaries. Return a complete replacement plan.\n\n"
                            f"Product model:\n{_compact_json(product)}\n\n"
                            f"System map:\n{_compact_json(system_map)}\n\n"
                            f"Previous plan:\n{_compact_json(plan)}\n\n"
                            f"Plan review:\n{_compact_json(plan_review)}\n\n"
                            f"Available gate IDs: {gate_ids}"
                        ),
                        metadata={"gate_ids": gate_ids, "fixture_target": "manageroo_fixture.txt"},
                    )

            _topological_tasks(plan["tasks"])
            for task in plan["tasks"]:
                self._gates_for_ids(task["gate_ids"])
                for path in task["allowed_paths"] + task["context_paths"]:
                    safe_repo_relative(path)
            self._write_or_reuse_json("planning/task-plan.json", plan, lock=True)
            self._write_or_reuse_json("planning/plan-review.json", plan_review, lock=True)
            self._transition(Phase.CONTRACT_LOCKED, "Product, system map, and task plan are immutable")
            self.artifacts.verify_locked()

            self._transition(Phase.IMPLEMENTING, "Executing bounded tasks in dependency order")
            task_evidence: list[dict] = []
            for task in _topological_tasks(plan["tasks"]):
                task_artifact = f"implementation/tasks/{_artifact_fragment(str(task['id']))}.json"
                existing_task_evidence = self._artifact_json(task_artifact)
                if existing_task_evidence is not None:
                    task_evidence.append(existing_task_evidence)
                    continue
                self.artifacts.verify_locked()
                before_head = self.mirror.head()
                requests = []
                seen = set()
                for path in task.get("context_paths", []) + task.get("allowed_paths", []):
                    if path in seen or not (self.workspace / path).is_file():
                        continue
                    seen.add(path)
                    requests.append(
                        ContextRequest(
                            path=path,
                            reason=f"Task {task['id']} implementation context.",
                            required=path in task.get("context_paths", []),
                            priority=100 if path in task.get("context_paths", []) else 80,
                        )
                    )
                implementation = self._call(
                    role="implementer",
                    schema="agent-result.schema.json",
                    instructions=(
                        "# Bounded implementation role\n\n"
                        "Implement exactly one locked task. You may inspect the repository, but may "
                        "edit only allowed_paths. Do not redesign adjacent systems, alter the locked "
                        "plan, weaken tests, commit, push, or change .git/.manageroo. Use existing repository "
                        "patterns and the reuse decisions. Return an exact list of every changed file.\n\n"
                        f"Product model:\n{_compact_json(product)}\n\n"
                        f"Task:\n{_compact_json(task)}\n\n"
                        f"Global invariants:\n{_compact_json(plan['global_invariants'])}"
                    ),
                    context=requests,
                    sandbox="workspace-write",
                    metadata={"task": task},
                )
                if bool(self.config["safety"]["block_agent_commits"]) and self.mirror.head() != before_head:
                    raise SafetyError(f"Agent created a commit during task {task['id']}.")
                actual = self.mirror.changed_paths(before_head)
                ScopePolicy(tuple(task["allowed_paths"])).validate_paths(actual)
                declared = sorted(set(implementation.get("files_changed", [])))
                if sorted(actual) != declared:
                    raise SafetyError(
                        f"Task {task['id']} changed {actual} but declared {declared}. "
                        "Undeclared edits are blocked."
                    )
                task_gates = self._gates_for_ids(task["gate_ids"])
                gate_results = self._run_gates(task_gates, self.workspace)
                checkpoint = self.mirror.checkpoint(f"MANAGEROO controller checkpoint {task['id']}")
                evidence_entry = {
                    "task": task,
                    "implementation": implementation,
                    "changed_paths": actual,
                    "gates": gate_results,
                    "checkpoint": checkpoint,
                }
                self.artifacts.write_json(task_artifact, evidence_entry, lock=True)
                task_evidence.append(evidence_entry)
            self._write_or_reuse_json("implementation/task-evidence.json", task_evidence, lock=True)

            self._transition(Phase.VERIFYING, "Running the complete deterministic gate catalog")
            all_gates = list(self._gate_catalog().values())
            global_gate_results = self._run_gates(all_gates, self.workspace)
            self.artifacts.write_json("verification/gates.json", global_gate_results)

            if any(argv for _, argv in self._external_review_repair_commands()):
                self._transition(
                    Phase.REPAIRING,
                    "Running command-owned AUTOREVIEW and Clawpatch lanes",
                )
                external_review_repair = self._run_external_review_repair_lanes(
                    brief=brief,
                    plan=plan,
                    gate_results=global_gate_results,
                )
                self._transition(
                    Phase.VERIFYING,
                    "Command-owned review/repair lanes completed",
                )
                if external_review_repair and external_review_repair["summary"]["changed_paths"]:
                    global_gate_results = self._run_gates(all_gates, self.workspace)
                    self.artifacts.write_json("verification/gates.json", global_gate_results)

            changed_paths = self.mirror.changed_paths(self.mirror.baseline_commit)
            self._transition(Phase.REVIEWING, "Launching isolated fresh-context review")
            review = self._perform_review(plan, product, global_gate_results, changed_paths)

            max_repairs = int(self.config["project"]["max_repair_cycles"])
            while any(item.get("blocking") for item in review.get("findings", [])):
                if self.state.repair_cycles >= max_repairs:
                    raise ValidationError("Blocking review findings did not converge within repair limit.")
                self.state.repair_cycles += 1
                self.state.save(self.state_path)
                self._transition(Phase.REPAIRING, "Repairing verified blocking findings")
                before_head = self.mirror.head()
                finding_paths = sorted(
                    {item["path"] for item in review["findings"] if item.get("blocking") and item.get("path")}
                )
                allowed = sorted(
                    set(finding_paths)
                    | {path for task in plan["tasks"] for path in task["allowed_paths"]}
                )
                requests = [
                    ContextRequest(
                        path=path,
                        reason="Verified blocking review finding.",
                        required=True,
                        priority=100,
                    )
                    for path in finding_paths
                    if (self.workspace / path).is_file()
                ]
                repair = self._call(
                    role="repairer",
                    schema="agent-result.schema.json",
                    instructions=(
                        "# Verified-finding repair role\n\n"
                        "Repair only the verified blocking findings. Do not broaden the product, "
                        "change locked requirements, or perform cleanup unrelated to a finding. "
                        "Return every changed file exactly. Do not commit.\n\n"
                        f"Review:\n{_compact_json(review)}\n\n"
                        f"Allowed paths:\n{allowed}\n\n"
                        f"Locked plan:\n{_compact_json(plan)}"
                    ),
                    context=requests,
                    sandbox="workspace-write",
                    metadata={"task": {"allowed_paths": allowed}},
                )
                if self.mirror.head() != before_head:
                    raise SafetyError("Repair agent created an unauthorized commit.")
                actual = self.mirror.changed_paths(before_head)
                ScopePolicy(tuple(allowed)).validate_paths(actual)
                if sorted(actual) != sorted(set(repair.get("files_changed", []))):
                    raise SafetyError("Repair agent did not declare its exact changed-file set.")
                self.mirror.checkpoint(f"MANAGEROO controller repair {self.state.repair_cycles}")
                self._transition(Phase.VERIFYING, "Re-running all gates after repair")
                global_gate_results = self._run_gates(all_gates, self.workspace)
                changed_paths = self.mirror.changed_paths(self.mirror.baseline_commit)
                self._transition(Phase.REVIEWING, "Re-reviewing repaired result")
                review = self._perform_review(plan, product, global_gate_results, changed_paths)

            self._transition(Phase.DEMONSTRATING, "Executing product-level demonstration evidence")
            demonstration = plan["demonstration"]
            demonstration_gates = self._gates_for_ids(demonstration.get("gate_ids", []))
            if (
                bool(self.config["project"]["require_demonstration"])
                and demonstration.get("required", True)
                and not demonstration_gates
            ):
                raise GateFailure("Product demonstration is required but has no configured gate IDs.")
            demo_results = (
                self._run_gates(demonstration_gates, self.workspace)
                if demonstration_gates
                else []
            )
            self.artifacts.write_json(
                "verification/demonstration.json",
                {
                    "required": demonstration.get("required", True),
                    "product_evidence": demonstration.get("product_evidence", []),
                    "gates": demo_results,
                },
            )

            self._transition(Phase.DELIVERING, "Producing patch, evidence ledger, and product report")
            patch_path = self.mirror.write_patch(self.run_root / "delivery" / "final.patch")
            should_apply = (
                bool(self.config["project"]["apply_on_success"])
                if apply_on_success is None
                else apply_on_success
            )
            if should_apply:
                self.mirror.apply_patch_to_source(patch_path)

            acceptance = [
                {"description": item, "passed": True}
                for item in product.get("acceptance_outcomes", [])
            ]
            result.update(
                {
                    "status": "COMPLETE",
                    "product_summary": product.get("goal", ""),
                    "acceptance": acceptance,
                    "reuse": reuse.get("decisions", []),
                    "gates": global_gate_results,
                    "review": review,
                    "external_review_repair": external_review_repair,
                    "files_changed": changed_paths,
                    "risks": [
                        risk
                        for task in task_evidence
                        for risk in task["implementation"].get("risks", [])
                    ],
                    "evidence_paths": {
                        "run_root": str(self.run_root),
                        "patch": str(patch_path),
                        "artifact_ledger": str(self.artifacts.ledger_path),
                        "state": str(self.state_path),
                    },
                    "applied_to_source": should_apply,
                    "finished_at": utc_now(),
                }
            )
            result["learning"] = self._record_learning(
                result=result,
                inventory=raw_inventory,
                external_intelligence=external_intelligence,
                external_review_repair=external_review_repair,
            )
            report_path = self.run_root / "delivery" / "FINAL-REPORT.md"
            final_result_path = self.run_root / "delivery" / "final-result.json"
            markdown = write_report(report_path, result)
            atomic_write_json(final_result_path, result)
            external_capture = self._capture_external_outcome(
                report_path=report_path,
                result_path=final_result_path,
                patch_path=patch_path,
                result=result,
            )
            if external_capture is not None:
                result["external_capture"] = external_capture
                markdown = write_report(report_path, result)
                atomic_write_json(final_result_path, result)
            obsidian.export(f"{self.run_id}.md", markdown)
            self._transition(Phase.COMPLETE, "All required evidence passed; delivery complete")
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
            try:
                result["learning"] = self._record_learning(
                    result=result,
                    inventory=raw_inventory,
                    external_intelligence=external_intelligence,
                    external_review_repair=external_review_repair,
                )
            except Exception as learning_exc:
                result["learning_error"] = f"{type(learning_exc).__name__}: {learning_exc}"
            failure_dir = self.run_root / "delivery"
            failure_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(failure_dir / "failure.json", result)
            write_report(failure_dir / "FINAL-REPORT.md", result)
            raise
