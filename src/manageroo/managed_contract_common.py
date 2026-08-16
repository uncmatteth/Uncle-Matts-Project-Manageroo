from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, SafetyError
from .runner import CommandRunner
from .util import (
    atomic_write_json,
    canonical_json_bytes,
    sha256_file,
    sha256_text,
    utc_now,
)


REQUEST_METADATA_SCHEMA_VERSION = 1
COMPLETION_RECEIPT_SCHEMA_VERSION = 1
EXECUTION_INTENT_MUTATING = "mutating-work"
EXECUTION_INTENT_READ_ONLY = "read-only-repository-analysis"

_COMPLETION_BINDING_FIELDS = (
    "authorized_run_id",
    "completion_receipt_path",
    "completion_receipt_sha256",
    "completed_run_root",
)


def _unsigned(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "signature"}


def _payload_signature(value: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical_json_bytes(_unsigned(value)), hashlib.sha256).hexdigest()


def _signed_payload(value: dict[str, Any], key: bytes) -> dict[str, Any]:
    payload = dict(value)
    payload["signature"] = _payload_signature(payload, key)
    return payload


def _verify_signed_payload(value: Any, key: bytes, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must contain a JSON object.")
    signature = value.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, _payload_signature(value, key)
    ):
        raise ConfigurationError(f"{label} signature is invalid.")
    return value


def _read_regular_bytes(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ConfigurationError(f"Controller proof is not a regular file: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ConfigurationError(f"Controller proof is too large: {path}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or after.st_nlink != 1
        ):
            raise ConfigurationError(f"Controller proof changed while reading: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_regular_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(_read_regular_bytes(path).decode("utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"{label} is missing: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigurationError(f"{label} is not valid UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{label} contains invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError(f"{label} must contain a JSON object: {path}")
    return payload


def _request_metadata_path(request_path: Path) -> Path:
    return request_path.with_suffix(".request.json")


def _request_state_root(request_path: Path) -> Path:
    requests = request_path.parent
    if requests.name != "requests":
        raise ConfigurationError("Managed request is not inside the continuity requests directory.")
    return requests.parent


def _clear_completion_binding(state: dict[str, Any]) -> None:
    for field in _COMPLETION_BINDING_FIELDS:
        state.pop(field, None)


def _persist_request_metadata(
    root: Path, state: dict[str, Any], continuity_module: Any
) -> None:
    request_path = Path(str(state.get("managed_request_path") or ""))
    if not request_path.is_file():
        raise ConfigurationError("Managed request artifact is missing after persistence.")
    metadata_path = _request_metadata_path(request_path)
    metadata = {
        "schema_version": REQUEST_METADATA_SCHEMA_VERSION,
        "session_id": str(state.get("session_id") or ""),
        "session_id_sha256": sha256_text(str(state.get("session_id") or "")),
        "generation": int(state.get("generation", 1)),
        "request_path": str(request_path),
        "request_sha256": str(state.get("managed_request_sha256") or ""),
        "request_content_sha256": str(
            state.get("managed_request_content_sha256") or ""
        ),
        "repository_root": str(state.get("bound_repo") or ""),
        "execution_intent": str(
            state.get("execution_intent") or EXECUTION_INTENT_MUTATING
        ),
        "created_at": utc_now(),
    }
    signed = _signed_payload(
        metadata, continuity_module._authority_key(root, create=True)
    )
    atomic_write_json(metadata_path, signed)
    if os.name != "nt":
        os.chmod(metadata_path, 0o600)
    state["managed_request_metadata_path"] = str(metadata_path)
    state["managed_request_metadata_sha256"] = sha256_file(metadata_path)


def _load_request_metadata(
    request_path: Path, continuity_module: Any
) -> tuple[dict[str, Any], Path] | None:
    metadata_path = _request_metadata_path(request_path)
    if not metadata_path.is_file():
        return None
    root = _request_state_root(request_path)
    metadata = _verify_signed_payload(
        _read_regular_json(metadata_path, label="Managed request metadata"),
        continuity_module._authority_key(root, create=False),
        label="Managed request metadata",
    )
    if metadata.get("schema_version") != REQUEST_METADATA_SCHEMA_VERSION:
        raise ConfigurationError("Managed request metadata schema is unsupported.")
    session_id = str(metadata.get("session_id") or "")
    generation = metadata.get("generation")
    if not session_id or type(generation) is not int or generation < 1:
        raise ConfigurationError("Managed request metadata identity is invalid.")
    session_identity = sha256_text(session_id)
    if str(metadata.get("session_id_sha256") or "") != session_identity:
        raise ConfigurationError("Managed request metadata session identity is invalid.")
    expected_name = f"{session_identity}-g{generation}.md"
    if request_path.name != expected_name:
        raise ConfigurationError("Managed request metadata was replayed to another generation.")
    if Path(str(metadata.get("request_path") or "")) != request_path:
        raise ConfigurationError("Managed request metadata points to another request file.")
    if sha256_file(request_path) != str(metadata.get("request_sha256") or ""):
        raise ConfigurationError("Managed request bytes no longer match their metadata.")
    if sha256_text(request_path.read_text(encoding="utf-8").strip()) != str(
        metadata.get("request_content_sha256") or ""
    ):
        raise ConfigurationError("Managed request content no longer matches its metadata.")
    return metadata, root


def _artifact_digest(path: Path, *, required: bool = True) -> str:
    if not path.is_file():
        if required:
            raise SafetyError(f"Required completion artifact is missing: {path}")
        return ""
    return sha256_file(path)


def _git_head(repo: Path, runner: CommandRunner) -> str:
    result = runner.run(["git", "rev-parse", "HEAD"], cwd=repo, timeout_seconds=60)
    if not result.passed or not result.stdout.strip():
        raise SafetyError("Could not resolve the repository Git HEAD for managed proof.")
    return result.stdout.strip()
