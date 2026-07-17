from __future__ import annotations

from typing import Any

from .errors import SafetyError, ValidationError
from .policy import ScopePolicy
from .util import safe_repo_relative


def _checkpoint_message(name: str) -> str:
    return f"MANAGEROO command-owned {name} repair lane"


def _existing_checkpoint(orchestrator: Any, name: str) -> tuple[str, list[str]] | None:
    assert orchestrator.workspace is not None
    message = _checkpoint_message(name)
    result = orchestrator.runner.run(
        ["git", "log", "--format=%H%x00%s"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not result.passed:
        raise SafetyError(
            f"Could not inspect command-owned {name} repair checkpoints: {result.stderr}"
        )
    commits = []
    for line in result.stdout.splitlines():
        commit, separator, subject = line.partition("\0")
        if separator and subject == message and commit.strip():
            commits.append(commit.strip())
    if not commits:
        return None
    if len(commits) != 1:
        raise SafetyError(
            f"Command-owned {name} repair lane has ambiguous duplicate checkpoints: {commits}"
        )
    checkpoint = commits[0]
    changed = orchestrator.runner.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", checkpoint],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not changed.passed:
        raise SafetyError(
            f"Could not reconstruct command-owned {name} repair evidence: {changed.stderr}"
        )
    return checkpoint, sorted(
        {line.strip() for line in changed.stdout.splitlines() if line.strip()}
    )


def run_external_review_repair_lanes(
    self: Any,
    *,
    brief: str,
    plan: dict,
    gate_results: list[dict],
) -> dict | None:
    """Run or safely resume command-owned repair lanes.

    A successful mutating command is committed by the Manageroo controller. If the
    process dies after that checkpoint but before the aggregate evidence artifact is
    written, continuation reconstructs evidence from the unique checkpoint instead of
    rerunning the external command against an already-modified workspace.
    """

    assert self.workspace is not None
    existing = self._artifact_json("review/external-review-repair.json")
    if existing is not None:
        return existing

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

    records: list[dict] = []
    failed: list[str] = []
    for name, argv_template in commands:
        resumed = _existing_checkpoint(self, name)
        if resumed is not None:
            checkpoint, changed_paths = resumed
            ScopePolicy(tuple(allowed_paths)).validate_paths(changed_paths)
            records.append(
                {
                    "name": name,
                    "enabled": True,
                    "ok": True,
                    "resumed_from_checkpoint": True,
                    "checkpoint": checkpoint,
                    "command_owned_repair_lane": True,
                    "ai_freehand_repair_allowed": False,
                    "changed_paths": changed_paths,
                }
            )
            continue

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
            policy_error = (
                "External review/repair lane changed Git HEAD; the controller owns checkpoints."
            )
        try:
            ScopePolicy(tuple(allowed_paths)).validate_paths(changed_paths)
        except SafetyError as exc:
            policy_error = str(exc)
        if policy_error:
            record["ok"] = False
            record["policy_error"] = policy_error
        if record.get("ok") and changed_paths:
            record["checkpoint"] = self.mirror.checkpoint(_checkpoint_message(name))
        if not record.get("ok"):
            failed.append(name)
        records.append(record)

    changed_total = sorted(
        {
            path
            for record in records
            for path in list(record.get("changed_paths", []) or [])
        }
    )
    payload = {
        "summary": {
            "enabled": [name for name, _ in commands],
            "passed": [item["name"] for item in records if item.get("ok")],
            "failed": failed,
            "changed_paths": changed_total,
            "command_owned_repair_lanes": True,
            "ai_freehand_repair_allowed": False,
            "continuation_safe": True,
        },
        "records": records,
        "note": (
            "AUTOREVIEW and Clawpatch findings are not fed to the AI repairer. "
            "These configured commands own their review/repair lane; a nonzero exit, timeout, "
            "or policy error blocks the run with captured evidence. Existing unique controller "
            "checkpoints are resumed rather than rerun."
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


def install_external_repair_policy(orchestrator_module: Any) -> None:
    orchestrator_module.Orchestrator._run_external_review_repair_lanes = (
        run_external_review_repair_lanes
    )
