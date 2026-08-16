from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config_lock import config_mutation_lock
from .errors import ConfigurationError, SafetyError
from .managed_contract_common import (
    COMPLETION_RECEIPT_SCHEMA_VERSION,
    EXECUTION_INTENT_MUTATING,
    EXECUTION_INTENT_READ_ONLY,
    _artifact_digest,
    _git_head,
    _load_request_metadata,
    _read_regular_json,
    _signed_payload,
    _verify_signed_payload,
)
from .release_proof_policy import source_tree_digest
from .runner import CommandRunner
from .util import atomic_write_json, read_json, sha256_file, sha256_text, utc_now


def _write_completion_receipt(
    *,
    orchestrator: Any,
    request_metadata: dict[str, Any],
    state_root: Path,
    result: dict[str, Any],
    start_git_head: str,
    start_source_tree_sha256: str,
    continuity_module: Any,
) -> Path:
    run_id = str(result.get("run_id") or getattr(orchestrator, "run_id", "")).strip()
    if not run_id:
        raise SafetyError("Completed managed run has no run ID.")
    repo = orchestrator.source_repo.expanduser().resolve()
    expected_repo = Path(str(request_metadata.get("repository_root") or "")).expanduser().resolve(
        strict=False
    )
    if repo != expected_repo:
        raise SafetyError("Completed run repository does not match the bound managed request.")

    execution_intent = str(
        request_metadata.get("execution_intent") or EXECUTION_INTENT_MUTATING
    )
    patch_path = orchestrator.run_root / "delivery" / "final.patch"
    patch_sha256 = _artifact_digest(patch_path)
    current_git_head = _git_head(repo, orchestrator.runner)
    current_tree_sha256 = source_tree_digest(repo, orchestrator.runner)

    if execution_intent == EXECUTION_INTENT_MUTATING:
        if result.get("applied_to_source") is not True:
            raise SafetyError("Mutating managed work completed without applied source proof.")
        expected_tree = str(result.get("verified_source_tree_sha256") or "")
        expected_patch = str(result.get("final_patch_sha256") or "")
        if not expected_tree or expected_tree != current_tree_sha256:
            raise SafetyError(
                "Completed run source-tree proof does not match the applied repository."
            )
        if not expected_patch or expected_patch != patch_sha256:
            raise SafetyError("Completed run patch proof does not match the final patch.")
    elif execution_intent == EXECUTION_INTENT_READ_ONLY:
        if result.get("applied_to_source") is True:
            raise SafetyError("Read-only managed analysis applied source changes.")
        if patch_path.stat().st_size != 0:
            raise SafetyError("Read-only managed analysis produced a source patch.")
        if current_git_head != start_git_head or current_tree_sha256 != start_source_tree_sha256:
            raise SafetyError("Read-only managed analysis changed the source repository.")
    else:
        raise SafetyError(f"Unknown managed execution intent: {execution_intent}")

    run_root = orchestrator.run_root
    final_result_path = run_root / "delivery" / "final-result.json"
    conformance_path = run_root / "artifacts" / "verification" / "intent-conformance.json"
    gates_path = run_root / "artifacts" / "verification" / "gates.json"
    acceptance_path = run_root / "artifacts" / "verification" / "acceptance-evidence.json"
    review_path = run_root / "artifacts" / "review" / "review.json"
    persisted_result = read_json(final_result_path)
    conformance = read_json(conformance_path)
    if not isinstance(persisted_result, dict) or persisted_result.get("status") != "COMPLETE":
        raise SafetyError("Managed completion receipt requires a persisted COMPLETE result.")
    if not isinstance(conformance, dict) or conformance.get("status") != "passed":
        raise SafetyError("Managed completion receipt requires passing intent conformance.")

    receipt = {
        "schema_version": COMPLETION_RECEIPT_SCHEMA_VERSION,
        "authority": "manageroo-controller",
        "session_id_sha256": str(request_metadata.get("session_id_sha256") or ""),
        "request_generation": int(request_metadata.get("generation", 0)),
        "request_sha256": str(request_metadata.get("request_sha256") or ""),
        "request_content_sha256": str(
            request_metadata.get("request_content_sha256") or ""
        ),
        "execution_intent": execution_intent,
        "run_id": run_id,
        "repository_root": str(repo),
        "start_git_head": start_git_head,
        "current_git_head": current_git_head,
        "start_source_tree_sha256": start_source_tree_sha256,
        "applied_source_tree_sha256": current_tree_sha256,
        "final_patch_sha256": patch_sha256,
        "final_result_sha256": _artifact_digest(final_result_path),
        "intent_conformance_sha256": _artifact_digest(conformance_path),
        "gates_sha256": _artifact_digest(gates_path),
        "acceptance_evidence_sha256": _artifact_digest(acceptance_path),
        "review_sha256": _artifact_digest(review_path),
        "applied_to_source": bool(result.get("applied_to_source")),
        "created_at": utc_now(),
    }
    receipt_path = run_root / "delivery" / "completion-receipt.json"
    atomic_write_json(
        receipt_path,
        _signed_payload(
            receipt, continuity_module._authority_key(state_root, create=False)
        ),
    )
    if os.name != "nt":
        os.chmod(receipt_path, 0o600)

    session_id = str(request_metadata.get("session_id") or "")
    if session_id:
        state_path = continuity_module._state_path(state_root, session_id)
        with config_mutation_lock(state_path):
            state = continuity_module._read_state(state_root, session_id)
            if (
                isinstance(state, dict)
                and int(state.get("generation", 0))
                == int(request_metadata.get("generation", -1))
                and str(state.get("managed_request_sha256") or "")
                == str(request_metadata.get("request_sha256") or "")
                and str(state.get("bound_repo") or "") == str(repo)
            ):
                state.update(
                    {
                        "authorized_run_id": run_id,
                        "completion_receipt_path": str(receipt_path),
                        "completion_receipt_sha256": sha256_file(receipt_path),
                        "completed_run_root": str(run_root),
                        "updated_at": utc_now(),
                    }
                )
                continuity_module._save_state_locked(state_root, state)
    return receipt_path


def _verify_completion_receipt(
    state: dict[str, Any], continuity_module: Any
) -> dict[str, Any] | None:
    request_path = Path(str(state.get("managed_request_path") or ""))
    if not request_path.is_file():
        return None
    try:
        metadata_loaded = _load_request_metadata(request_path, continuity_module)
    except (OSError, ConfigurationError, UnicodeDecodeError):
        return None
    if metadata_loaded is None:
        return None
    metadata, state_root = metadata_loaded
    run_id = str(state.get("authorized_run_id") or "").strip()
    receipt_path = Path(str(state.get("completion_receipt_path") or ""))
    expected_receipt_sha256 = str(state.get("completion_receipt_sha256") or "")
    bound_repo_text = str(state.get("bound_repo") or "")
    if not run_id or not expected_receipt_sha256 or not bound_repo_text:
        return None
    repo = Path(bound_repo_text).expanduser().resolve(strict=False)
    expected_receipt_path = (
        repo / ".manageroo" / "runs" / run_id / "delivery" / "completion-receipt.json"
    ).resolve(strict=False)
    if receipt_path.resolve(strict=False) != expected_receipt_path:
        return None
    try:
        if sha256_file(receipt_path) != expected_receipt_sha256:
            return None
        receipt = _verify_signed_payload(
            _read_regular_json(receipt_path, label="Managed completion receipt"),
            continuity_module._authority_key(state_root, create=False),
            label="Managed completion receipt",
        )
    except (OSError, ConfigurationError):
        return None
    if receipt.get("schema_version") != COMPLETION_RECEIPT_SCHEMA_VERSION:
        return None
    required_equal = {
        "session_id_sha256": sha256_text(str(state.get("session_id") or "")),
        "request_generation": int(state.get("generation", 0)),
        "request_sha256": str(state.get("managed_request_sha256") or ""),
        "request_content_sha256": str(
            state.get("managed_request_content_sha256") or ""
        ),
        "execution_intent": str(
            state.get("execution_intent") or EXECUTION_INTENT_MUTATING
        ),
        "run_id": run_id,
        "repository_root": str(repo),
    }
    if any(receipt.get(key) != value for key, value in required_equal.items()):
        return None
    if (
        metadata.get("generation") != receipt.get("request_generation")
        or metadata.get("request_sha256") != receipt.get("request_sha256")
        or metadata.get("repository_root") != receipt.get("repository_root")
    ):
        return None

    run_root = repo / ".manageroo" / "runs" / run_id
    artifacts = {
        "final_patch_sha256": run_root / "delivery" / "final.patch",
        "final_result_sha256": run_root / "delivery" / "final-result.json",
        "intent_conformance_sha256": run_root
        / "artifacts"
        / "verification"
        / "intent-conformance.json",
        "gates_sha256": run_root / "artifacts" / "verification" / "gates.json",
        "acceptance_evidence_sha256": run_root
        / "artifacts"
        / "verification"
        / "acceptance-evidence.json",
        "review_sha256": run_root / "artifacts" / "review" / "review.json",
    }
    try:
        if any(
            not path.is_file() or sha256_file(path) != str(receipt.get(field) or "")
            for field, path in artifacts.items()
        ):
            return None
        result = read_json(artifacts["final_result_sha256"])
        conformance = read_json(artifacts["intent_conformance_sha256"])
        expected_applied = (
            receipt.get("execution_intent") == EXECUTION_INTENT_MUTATING
        )
        if (
            not isinstance(result, dict)
            or result.get("status") != "COMPLETE"
            or str(result.get("run_id") or "") != run_id
            or bool(result.get("applied_to_source")) != expected_applied
            or bool(receipt.get("applied_to_source")) != expected_applied
            or not isinstance(conformance, dict)
            or conformance.get("status") != "passed"
        ):
            return None
        runner = CommandRunner()
        if _git_head(repo, runner) != str(receipt.get("current_git_head") or ""):
            return None
        if source_tree_digest(repo, runner) != str(
            receipt.get("applied_source_tree_sha256") or ""
        ):
            return None
    except (OSError, RuntimeError, SafetyError, ValueError, json.JSONDecodeError):
        return None
    return {"run_root": str(run_root), "result": result, "receipt": receipt}


def install_managed_completion_policy(
    orchestrator_module: Any, continuity_module: Any
) -> None:
    orchestrator_class = orchestrator_module.Orchestrator
    if getattr(
        orchestrator_class, "_manageroo_managed_completion_policy_installed", False
    ):
        return
    original_run = orchestrator_class.run

    def run_with_managed_contract(self: Any, *args: Any, **kwargs: Any):
        # Recovery is local and must run before integration validation.
        self._recover_incomplete_delivery()
        brief_value = kwargs.get("brief_path")
        if brief_value is None and args:
            brief_value = args[0]
        request_metadata: dict[str, Any] | None = None
        state_root: Path | None = None
        start_git_head = ""
        start_source_tree_sha256 = ""
        if brief_value is not None:
            brief_path = Path(brief_value).expanduser().resolve()
            loaded = _load_request_metadata(brief_path, continuity_module)
            if loaded is not None:
                request_metadata, state_root = loaded
                bound = Path(
                    str(request_metadata.get("repository_root") or "")
                ).expanduser().resolve(strict=False)
                if bound != self.source_repo.expanduser().resolve():
                    raise SafetyError(
                        "Managed request repository binding does not match this run."
                    )
                start_git_head = _git_head(self.source_repo, self.runner)
                start_source_tree_sha256 = source_tree_digest(
                    self.source_repo, self.runner
                )
        result = original_run(self, *args, **kwargs)
        if (
            request_metadata is not None
            and state_root is not None
            and isinstance(result, dict)
            and result.get("status") == "COMPLETE"
        ):
            _write_completion_receipt(
                orchestrator=self,
                request_metadata=request_metadata,
                state_root=state_root,
                result=result,
                start_git_head=start_git_head,
                start_source_tree_sha256=start_source_tree_sha256,
                continuity_module=continuity_module,
            )
        return result

    orchestrator_class.run = run_with_managed_contract
    orchestrator_class._manageroo_managed_completion_policy_installed = True
