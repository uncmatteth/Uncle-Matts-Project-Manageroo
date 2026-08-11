from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .util import safe_repo_relative


MAX_DOCUMENTS = 64
MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_HEADINGS = 40
OPENING_CHARS = 2_000
CLOSING_CHARS = 1_000


def _regular_document(workspace: Path, relative: str) -> tuple[Path, bytes]:
    safe = safe_repo_relative(relative)
    path = workspace / safe
    try:
        state = path.lstat()
    except OSError as exc:
        raise ConfigurationError(f"Document lane could not inspect {safe}: {exc}") from exc
    if not stat.S_ISREG(state.st_mode) or state.st_nlink != 1:
        raise ConfigurationError(f"Document lane requires a single-link regular file: {safe}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ConfigurationError(f"Document lane path escapes the workspace: {safe}") from exc
    if state.st_size > MAX_TEXT_BYTES:
        raise ConfigurationError(
            f"Document lane file exceeds the {MAX_TEXT_BYTES}-byte extraction limit: {safe}"
        )
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f"Document lane could not read {safe}: {exc}") from exc
    current = resolved.stat()
    if (
        current.st_dev != state.st_dev
        or current.st_ino != state.st_ino
        or current.st_size != state.st_size
        or current.st_mtime_ns != state.st_mtime_ns
    ):
        raise ConfigurationError(f"Document changed while the document lane read it: {safe}")
    return resolved, data


def _pdf_excerpt(data: bytes) -> tuple[str, str]:
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "3", "-", "-"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", f"PDF text extraction unavailable: {exc}"
    if result.returncode != 0:
        error = (result.stderr or b"").decode("utf-8", errors="replace")
        return "", f"PDF text extraction failed: {error.strip()[:500]}"
    opening = (result.stdout or b"").decode("utf-8", errors="replace")
    return opening[:OPENING_CHARS], ""


def analyze_document_manifest(manifest_path: Path, workspace_path: Path) -> dict[str, Any]:
    manifest = manifest_path.expanduser().resolve(strict=True)
    workspace = workspace_path.expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ConfigurationError(f"Document workspace is not a directory: {workspace}")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Document manifest is unreadable: {manifest}") from exc
    files = payload.get("files", []) if isinstance(payload, dict) else []
    if not isinstance(files, list):
        raise ConfigurationError("Document manifest files must be an array.")
    if len(files) > MAX_DOCUMENTS:
        raise ConfigurationError(
            f"Document manifest exceeds the {MAX_DOCUMENTS}-document analysis limit."
        )

    documents: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict) or not item.get("path"):
            raise ConfigurationError("Document manifest contains an invalid file record.")
        relative = safe_repo_relative(str(item["path"]))
        _, data = _regular_document(workspace, relative)
        expected_hash = str(item.get("sha256") or "")
        actual_hash = hashlib.sha256(data).hexdigest()
        if expected_hash and expected_hash != actual_hash:
            raise ConfigurationError(f"Document manifest hash no longer matches {relative}.")
        language = str(item.get("language") or "")
        note = ""
        if language == "pdf":
            opening, note = _pdf_excerpt(data)
            closing = ""
            headings: list[str] = []
        else:
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            headings = [line.strip() for line in lines if line.lstrip().startswith("#")][
                :MAX_HEADINGS
            ]
            opening = text[:OPENING_CHARS]
            closing = text[-CLOSING_CHARS:] if len(text) > OPENING_CHARS else ""
        documents.append(
            {
                "path": relative,
                "language": language,
                "long_document": bool(item.get("long_document")),
                "sha256": actual_hash,
                "headings": headings,
                "opening_excerpt": opening,
                "closing_excerpt": closing,
                "note": note,
            }
        )
    return {
        "ok": True,
        "schema_version": 1,
        "summary": {
            "requested": len(files),
            "analyzed": len(documents),
            "long_documents": sum(1 for item in documents if item["long_document"]),
        },
        "documents": documents,
        "rules": payload.get("rules", []) if isinstance(payload, dict) else [],
        "note": (
            "Bounded document evidence only. Exact wording and current source files remain authoritative."
        ),
    }
