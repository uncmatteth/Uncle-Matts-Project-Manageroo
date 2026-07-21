from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .branding import PUBLIC_COMMAND
from .errors import SafetyError


_SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|[_-])(?:api[_-]?key|token|password|secret|authorization)(?:$|[_-])"
)
_SECRET_PATTERNS = [
    re.compile(
        r'''(?ix)
        (?P<prefix>["']?(?:api[_-]?key|token|password|secret|authorization)["']?\s*[:=]\s*)
        (?P<value>
            "(?:\\.|[^"\\])*"
            |
            '(?:\\.|[^'\\])*'
            |
            [^\s,;}] +
        )
        '''.replace("[^\\s,;}] +", "[^\\s,;}]+")
    ),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+"),
]
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:/")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{PUBLIC_COMMAND}-{stamp}-{os.urandom(3).hex()}"


def slugify(value: str, max_length: int = 64) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return (value or "item")[:max_length].rstrip("-")


def canonical_json_bytes(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(data: Any) -> str:
    return sha256_bytes(canonical_json_bytes(data))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<REDACTED>" if _SECRET_KEY_RE.search(str(key)) else _redact_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    return value


def redact_text(text: str) -> str:
    # Structurally redact complete JSON payloads first so quoted keys and values are
    # handled correctly. Fall back to conservative text patterns for logs and prose.
    stripped = text.strip()
    if stripped:
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            redacted_json = json.dumps(
                _redact_json_value(parsed),
                ensure_ascii=False,
                separators=(",", ":") if "\n" not in text else None,
                indent=2 if "\n" in text else None,
            )
            prefix = text[: len(text) - len(text.lstrip())]
            suffix = text[len(text.rstrip()) :]
            return prefix + redacted_json + suffix

    redacted = text
    for pattern in _SECRET_PATTERNS:
        if "bearer" in pattern.pattern.lower():
            redacted = pattern.sub("Bearer <REDACTED>", redacted)
        else:
            redacted = pattern.sub(lambda m: f"{m.group('prefix')}<REDACTED>", redacted)
    return redacted


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_within(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafetyError(f"Path escapes allowed root: {candidate}") from exc
    return candidate


def safe_repo_relative(value: str) -> str:
    normalized = str(value).replace("\\", "/")
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or _WINDOWS_ABSOLUTE_RE.match(normalized)
        or pure.is_absolute()
        or ".." in pure.parts
    ):
        raise SafetyError(f"Unsafe repository-relative path: {value!r}")
    return str(pure)


def file_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def copy_file_preserving_mode(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    destination.chmod(file_mode(source))
