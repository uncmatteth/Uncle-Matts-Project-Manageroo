from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .discovery_preflight import build_discovery_preflight
from .errors import BlockingDecisionError, ValidationError
from .system_capacity import host_capacity
from .util import atomic_write_json, atomic_write_text, read_json, utc_now


def _decision_paths(run_root: Path) -> tuple[Path, Path, Path, Path]:
    planning = run_root / "artifacts" / "planning"
    return (
        planning / "blocking-decisions.json",
        planning / "resolved-decisions.json",
        planning / "product-model.json",
        planning / "BLOCKING-QUESTIONS.md",
    )


def _resolution_path(run_root: Path) -> Path:
    return run_root / "artifacts" / "planning" / "decision-resolution.json"


def decisions_fully_resolved(run_root: Path) -> bool:
    _, _, product_path, _ = _decision_paths(run_root)
    if not _resolution_path(run_root).is_file() or not product_path.is_file():
        return False
    product = read_json(product_path)
    decisions = list(product.get("blocking_decisions", []) or [])
    return bool(decisions) and all(bool(item.get("chosen")) for item in decisions)


def render_blocking_questions(run_root: Path) -> Path | None:
    blocking_path, _, _, markdown_path = _decision_paths(run_root)
    if not blocking_path.is_file() or decisions_fully_resolved(run_root):
        return None
    payload = read_json(blocking_path)
    decisions = list(payload.get("decisions", []) or [])
    lines = [
        "# Manageroo blocking questions",
        "",
        (
            "These are the decisions Manageroo could not safely infer from the repository "
            "or adopt as a reversible default."
        ),
        (
            "Answer them with `manageroo decisions answer <run-id> --repo /path/to/repo`, "
            "then continue the same run."
        ),
        "",
    ]
    for index, item in enumerate(decisions, 1):
        lines.extend(
            [
                f"## {index}. {item.get('question', 'Decision required')}",
                "",
                f"**Why this matters:** {item.get('why', 'No explanation provided.')}",
                "",
                f"**Category:** {item.get('category', 'product')}",
                "",
                f"**Recommended:** {item.get('recommended') or 'No safe default available.'}",
                "",
                "**Options:**",
            ]
        )
        for option in item.get("options", []):
            lines.append(f"- {option}")
        lines.append("")
    atomic_write_text(markdown_path, "\n".join(lines).rstrip() + "\n")
    return markdown_path


def _consume_resolved_input(resolved_path: Path, markdown_path: Path) -> None:
    if markdown_path.exists():
        markdown_path.unlink()
    if resolved_path.exists():
        resolved_path.unlink()


def apply_resolved_decisions(
    run_root: Path,
    *,
    artifact_store: Any | None = None,
) -> bool:
    _, resolved_path, product_path, markdown_path = _decision_paths(run_root)
    if not resolved_path.is_file():
        return False
    if decisions_fully_resolved(run_root):
        _consume_resolved_input(resolved_path, markdown_path)
        return True
    if not product_path.is_file():
        raise ValidationError("Resolved decisions exist but the saved product model is missing.")

    resolved = read_json(resolved_path)
    answers = {
        str(item.get("id")): str(item.get("chosen"))
        for item in resolved.get("answers", [])
        if item.get("id") and item.get("chosen")
    }
    if not answers:
        raise ValidationError("Resolved decisions file contains no answers.")

    product = read_json(product_path)
    decisions = list(product.get("blocking_decisions", []) or [])
    unresolved: list[str] = []
    applied: list[dict[str, str]] = []
    for decision in decisions:
        decision_id = str(decision.get("id") or "")
        existing = str(decision.get("chosen") or "")
        chosen = answers.get(decision_id)
        if existing:
            if chosen and chosen != existing:
                raise ValidationError(
                    f"Resolved decision {decision_id!r} conflicts with the already-applied "
                    f"choice {existing!r}."
                )
            if chosen:
                applied.append({"id": decision_id, "chosen": existing})
            continue
        if not chosen:
            unresolved.append(decision_id or str(decision.get("question") or "unknown"))
            continue
        options = [str(item) for item in decision.get("options", [])]
        if chosen not in options:
            raise ValidationError(
                f"Resolved decision {decision_id!r} chose {chosen!r}, which is not one of "
                f"the allowed options: {options}"
            )
        decision["chosen"] = chosen
        decision["resolution_source"] = "operator answer via manageroo decisions"
        applied.append({"id": decision_id, "chosen": chosen})

    if unresolved:
        raise ValidationError(
            "Not all blocking decisions have answers: " + ", ".join(unresolved)
        )

    resolution = {"applied_at": utc_now(), "answers": applied}
    if artifact_store is None:
        atomic_write_json(product_path, product)
        atomic_write_json(_resolution_path(run_root), resolution)
    else:
        artifact_store.write_json(
            "planning/product-model.json",
            product,
            lock=True,
        )
        artifact_store.write_json(
            "planning/decision-resolution.json",
            resolution,
            lock=True,
        )
    _consume_resolved_input(resolved_path, markdown_path)
    return True


def install_discovery_policy(orchestrator_module: Any) -> None:
    cls = orchestrator_module.Orchestrator
    if getattr(cls, "_manageroo_discovery_policy_installed", False):
        return

    original_call = cls._call
    original_run = cls.run
    original_parallel = cls._max_parallel_agent_calls
    original_blocking_path = cls._blocking_decisions_path

    def current_capacity(self) -> dict:
        cached = getattr(self, "_manageroo_host_capacity", None)
        if cached is None:
            cached = host_capacity(self.source_repo)
            self._manageroo_host_capacity = cached
        return cached

    def capacity_bounded_parallel(self) -> int:
        configured = max(1, int(original_parallel(self)))
        recommended = int(
            current_capacity(self)
            .get("recommendations", {})
            .get("max_parallel_agent_calls", configured)
            or configured
        )
        return max(1, min(configured, recommended))

    def resolved_aware_blocking_path(self) -> Path:
        original = original_blocking_path(self)
        if decisions_fully_resolved(self.run_root):
            return original.with_name("blocking-decisions.resolved")
        return original

    def discovery_call(self, *args, **kwargs):
        role = kwargs.get("role")
        if role == "product-analyst":
            instructions = str(kwargs.get("instructions") or "")
            capacity = current_capacity(self)
            brief_marker = "Product brief:\n"
            brief = (
                instructions.split(brief_marker, 1)[1]
                if brief_marker in instructions
                else instructions
            )
            preflight = build_discovery_preflight(self.source_repo, brief, capacity)
            capacity_path = self.artifacts.root / "discovery" / "system-capacity.json"
            preflight_path = (
                self.artifacts.root / "discovery" / "unknown-unknowns-preflight.json"
            )
            if not capacity_path.is_file():
                self.artifacts.write_json(
                    "discovery/system-capacity.json",
                    capacity,
                    lock=True,
                )
            if not preflight_path.is_file():
                self.artifacts.write_json(
                    "discovery/unknown-unknowns-preflight.json",
                    preflight,
                    lock=True,
                )
            kwargs["instructions"] = (
                instructions
                + "\n\n# Manageroo unknown-unknowns preflight\n\n"
                + (
                    "Use the following deterministic preflight as a checklist, not as invented "
                    "product truth. Answer questions from repository evidence whenever possible. "
                    "Add relevant findings to constraints, assumptions, journeys, acceptance "
                    "outcomes, or blocking_decisions. Ask the operator only for genuinely "
                    "high-impact unresolved choices, and include a recommended option for every "
                    "blocking decision.\n\n"
                )
                + "Detected host capacity:\n"
                + json.dumps(capacity, indent=2, sort_keys=True)
                + "\n\nUnknown-unknowns checklist:\n"
                + json.dumps(preflight, indent=2, sort_keys=True)
            )
        return original_call(self, *args, **kwargs)

    def discovery_run(self, *args, **kwargs):
        if self.continuing:
            apply_resolved_decisions(
                self.run_root,
                artifact_store=self.artifacts,
            )
        try:
            return original_run(self, *args, **kwargs)
        except BlockingDecisionError as exc:
            render_blocking_questions(self.run_root)
            raise BlockingDecisionError(
                f"{exc} Answer with: manageroo decisions answer {self.run_id} "
                f"--repo {self.source_repo}. Then continue the same run."
            ) from exc

    cls._max_parallel_agent_calls = capacity_bounded_parallel
    cls._blocking_decisions_path = resolved_aware_blocking_path
    cls._call = discovery_call
    cls.run = discovery_run
    cls._manageroo_discovery_policy_installed = True
