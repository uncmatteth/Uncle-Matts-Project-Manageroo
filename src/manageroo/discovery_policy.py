from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from .config_lock import config_mutation_lock
from .discovery_preflight import build_discovery_preflight
from .errors import BlockingDecisionError, ValidationError
from .system_capacity import host_capacity
from .util import atomic_write_json, atomic_write_text, read_json, sha256_json, utc_now


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


def _validate_chosen_option(decision: dict[str, Any], chosen: str) -> None:
    options = [str(item) for item in decision.get("options", [])]
    if chosen not in options:
        raise ValidationError(
            f"Resolved decision {decision['id']!r} chose {chosen!r}, "
            f"which is not one of the allowed options: {options}"
        )


def decisions_fully_resolved(run_root: Path) -> bool:
    _, _, product_path, _ = _decision_paths(run_root)
    resolution_path = _resolution_path(run_root)
    if not resolution_path.is_file() or not product_path.is_file():
        return False
    product = read_json(product_path)
    if not isinstance(product, dict):
        return False
    decisions, decision_ids = _normalized_product_decisions(product)
    resolution = read_json(resolution_path)
    if not isinstance(resolution, dict):
        return False
    if resolution.get("product_model_sha256") != sha256_json(product):
        return False
    try:
        answers = _validated_answers(resolution, decision_ids)
    except ValidationError:
        return False
    if not decisions:
        return False
    for item in decisions:
        chosen = str(item.get("chosen") or "").strip()
        if not chosen:
            return False
        try:
            _validate_chosen_option(item, chosen)
        except ValidationError:
            return False
        if answers.get(str(item["id"])) != chosen:
            return False
    return True


def render_blocking_questions(run_root: Path) -> Path | None:
    blocking_path, _, _, markdown_path = _decision_paths(run_root)
    if not blocking_path.is_file() or decisions_fully_resolved(run_root):
        return None
    payload = read_json(blocking_path)
    if not isinstance(payload, dict):
        raise ValidationError("Blocking decision artifact must contain a JSON object.")
    decisions = list(payload.get("decisions", []) or [])
    lines = [
        "# Manageroo blocking questions", "",
        "These are the decisions Manageroo could not safely infer from the repository or adopt as a reversible default.",
        "Answer them with `manageroo decisions answer <run-id> --repo /path/to/repo`, then continue the same run.", "",
    ]
    for index, item in enumerate(decisions, 1):
        if not isinstance(item, dict):
            continue
        lines.extend([
            f"## {index}. {item.get('question', 'Decision required')}", "",
            f"**Why this matters:** {item.get('why', 'No explanation provided.')}", "",
            f"**Category:** {item.get('category', 'product')}", "",
            f"**Recommended:** {item.get('recommended') or 'No safe default available.'}", "",
            "**Options:**",
        ])
        for option in item.get("options", []):
            lines.append(f"- {option}")
        lines.append("")
    atomic_write_text(markdown_path, "\n".join(lines).rstrip() + "\n")
    return markdown_path


def _claim_resolved_input(resolved_path: Path) -> Path | None:
    if not resolved_path.is_file():
        return None
    claimed = resolved_path.with_name(
        f".{resolved_path.name}.claimed-{os.getpid()}-{uuid.uuid4().hex}.json"
    )
    try:
        os.replace(resolved_path, claimed)
    except FileNotFoundError:
        return None
    return claimed


def _recover_orphaned_claim(resolved_path: Path) -> None:
    claimed_paths = sorted(
        resolved_path.parent.glob(f".{resolved_path.name}.claimed-*.json")
    )
    if not claimed_paths:
        return
    if resolved_path.exists():
        if all(path.samefile(resolved_path) for path in claimed_paths):
            for path in claimed_paths:
                path.unlink()
            return
        raise ValidationError(
            "Multiple resolved decision submissions remain after an interrupted application."
        )
    if len(claimed_paths) != 1:
        raise ValidationError(
            "Multiple resolved decision submissions remain after an interrupted application."
        )
    try:
        os.link(claimed_paths[0], resolved_path, follow_symlinks=False)
    except FileExistsError as exc:
        raise ValidationError(
            "Multiple resolved decision submissions remain after an interrupted application."
        ) from exc
    claimed_paths[0].unlink()


def _finish_claim(claimed_path: Path, markdown_path: Path) -> None:
    if claimed_path.exists():
        claimed_path.unlink()
    if markdown_path.exists():
        markdown_path.unlink()


def _restore_failed_claim(claimed_path: Path, resolved_path: Path) -> None:
    if not claimed_path.exists():
        return
    if not resolved_path.exists():
        os.replace(claimed_path, resolved_path)
    # If a new answer file arrived while this claim was being processed, leave the
    # claimed file intact as evidence instead of deleting either operator submission.


def _validated_answers(resolved: dict[str, Any], decision_ids: set[str]) -> dict[str, str]:
    raw_answers = resolved.get("answers", [])
    if not isinstance(raw_answers, list):
        raise ValidationError("Resolved decisions answers must be a JSON array.")
    answers: dict[str, str] = {}
    seen: set[str] = set()
    for index, item in enumerate(raw_answers, 1):
        if not isinstance(item, dict):
            raise ValidationError(f"Resolved decision answer {index} must be an object.")
        decision_id = str(item.get("id") or "").strip()
        chosen = str(item.get("chosen") or "").strip()
        if not decision_id or not chosen:
            raise ValidationError(f"Resolved decision answer {index} requires non-empty id and chosen values.")
        if decision_id in seen:
            raise ValidationError(f"Resolved decisions contain duplicate answer id: {decision_id}")
        if decision_id not in decision_ids:
            raise ValidationError(f"Resolved decisions contain unknown decision id: {decision_id}")
        seen.add(decision_id)
        answers[decision_id] = chosen
    if not answers:
        raise ValidationError("Resolved decisions file contains no answers.")
    return answers


def _normalized_product_decisions(product: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    raw = product.get("blocking_decisions", [])
    if not isinstance(raw, list):
        raise ValidationError("Product blocking_decisions must be an array.")
    decisions: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValidationError(f"Product blocking decision {index} must be an object.")
        decision_id = str(item.get("id") or "").strip()
        if not decision_id:
            raise ValidationError(f"Product blocking decision {index} has no id.")
        if decision_id in ids:
            raise ValidationError(f"Product blocking decisions contain duplicate normalized id: {decision_id}")
        normalized = dict(item)
        normalized["id"] = decision_id
        decisions.append(normalized)
        ids.add(decision_id)
    return decisions, ids


def apply_resolved_decisions(run_root: Path, *, artifact_store: Any | None = None) -> bool:
    _, resolved_path, product_path, markdown_path = _decision_paths(run_root)
    if not resolved_path.parent.is_dir():
        return False
    resolution_path = _resolution_path(run_root)
    with config_mutation_lock(product_path):
        _recover_orphaned_claim(resolved_path)
        claimed_path = _claim_resolved_input(resolved_path)
        if claimed_path is None:
            return False
        try:
            if not product_path.is_file():
                raise ValidationError("Resolved decisions exist but the saved product model is missing.")
            resolved = read_json(claimed_path)
            if not isinstance(resolved, dict):
                raise ValidationError("Resolved decisions file must contain a JSON object.")
            product = read_json(product_path)
            if not isinstance(product, dict):
                raise ValidationError("Saved product model must contain a JSON object.")
            decisions, decision_ids = _normalized_product_decisions(product)
            answers = _validated_answers(resolved, decision_ids)

            unresolved: list[str] = []
            applied: list[dict[str, str]] = []
            product_changed = False
            for decision in decisions:
                decision_id = str(decision["id"]).strip()
                existing = str(decision.get("chosen") or "").strip()
                chosen = answers.get(decision_id)
                if existing:
                    _validate_chosen_option(decision, existing)
                    if chosen and chosen != existing:
                        raise ValidationError(
                            f"Resolved decision {decision_id!r} conflicts with the already-applied choice {existing!r}."
                        )
                    applied.append({"id": decision_id, "chosen": existing})
                    continue
                if not chosen:
                    unresolved.append(decision_id)
                    continue
                _validate_chosen_option(decision, chosen)
                decision["chosen"] = chosen
                decision["resolution_source"] = "operator answer via manageroo decisions"
                product_changed = True
                applied.append({"id": decision_id, "chosen": chosen})

            if unresolved:
                raise ValidationError("Not all blocking decisions have answers: " + ", ".join(unresolved))

            product["blocking_decisions"] = decisions
            resolution = {
                "applied_at": utc_now(),
                "answers": applied,
                "product_model_sha256": sha256_json(product),
            }
            if resolution_path.is_file():
                existing_resolution = read_json(resolution_path)
                if not isinstance(existing_resolution, dict) or (
                    existing_resolution.get("answers") != resolution["answers"]
                    or existing_resolution.get("product_model_sha256")
                    != resolution["product_model_sha256"]
                ):
                    raise ValidationError(
                        "Existing decision resolution does not match the current product model."
                    )

            if artifact_store is None:
                if product_changed:
                    atomic_write_json(product_path, product)
                if not resolution_path.is_file():
                    atomic_write_json(resolution_path, resolution)
            else:
                if product_changed:
                    artifact_store.write_json("planning/product-model.json", product, lock=True)
                if not resolution_path.is_file():
                    artifact_store.write_json("planning/decision-resolution.json", resolution, lock=True)
            _finish_claim(claimed_path, markdown_path)
            return True
        except Exception:
            _restore_failed_claim(claimed_path, resolved_path)
            raise


def install_discovery_policy(orchestrator_module: Any) -> None:
    cls = orchestrator_module.Orchestrator
    if getattr(cls, "_manageroo_discovery_policy_installed", False):
        return
    original_call = cls._call
    original_run = cls.run
    original_blocking_path = cls._blocking_decisions_path

    def current_capacity(self) -> dict:
        cached = getattr(self, "_manageroo_host_capacity", None)
        if cached is None:
            capacity_path = self.artifacts.root / "discovery" / "system-capacity.json"
            if capacity_path.is_file():
                cached = read_json(capacity_path)
                if not isinstance(cached, dict):
                    raise ValidationError(
                        "Saved system-capacity artifact is malformed; start a fresh run."
                    )
            else:
                cached = host_capacity(self.source_repo)
            self._manageroo_host_capacity = cached
        return cached

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
            brief = instructions.split(brief_marker, 1)[1] if brief_marker in instructions else instructions
            capacity_path = self.artifacts.root / "discovery" / "system-capacity.json"
            preflight_path = self.artifacts.root / "discovery" / "unknown-unknowns-preflight.json"
            if not capacity_path.is_file():
                self.artifacts.write_json("discovery/system-capacity.json", capacity, lock=True)
            if preflight_path.is_file():
                preflight = read_json(preflight_path)
                if not isinstance(preflight, dict):
                    raise ValidationError(
                        "Saved unknown-unknowns preflight artifact is malformed; start a fresh run."
                    )
            else:
                preflight = build_discovery_preflight(self.source_repo, brief, capacity)
                self.artifacts.write_json("discovery/unknown-unknowns-preflight.json", preflight, lock=True)
            kwargs["instructions"] = (
                instructions
                + "\n\n# Manageroo unknown-unknowns preflight\n\n"
                + "Use the following deterministic preflight as a checklist, not as invented product truth. "
                  "Answer questions from repository evidence whenever possible. Add relevant findings to constraints, assumptions, journeys, acceptance outcomes, or blocking_decisions. "
                  "Ask the operator only for genuinely high-impact unresolved choices, and include a recommended option for every blocking decision.\n\n"
                + "Development-host hardware profile (context only). This is NOT a Manageroo minimum requirement and MUST NOT be used to auto-tune Manageroo worker concurrency. "
                  "Use it only when the target project itself has hardware or local runtime requirements:\n"
                + json.dumps(capacity, indent=2, sort_keys=True)
                + "\n\nUnknown-unknowns checklist:\n"
                + json.dumps(preflight, indent=2, sort_keys=True)
            )
        return original_call(self, *args, **kwargs)

    def discovery_run(self, *args, **kwargs):
        if self.continuing:
            apply_resolved_decisions(self.run_root, artifact_store=self.artifacts)
        try:
            return original_run(self, *args, **kwargs)
        except BlockingDecisionError as exc:
            render_blocking_questions(self.run_root)
            raise BlockingDecisionError(
                f"{exc} Answer with: manageroo decisions answer {self.run_id} --repo {self.source_repo}. Then continue the same run."
            ) from exc

    cls._blocking_decisions_path = resolved_aware_blocking_path
    cls._call = discovery_call
    cls.run = discovery_run
    cls._manageroo_discovery_policy_installed = True
