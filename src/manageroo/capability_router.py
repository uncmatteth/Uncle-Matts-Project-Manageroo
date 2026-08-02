from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
import tomllib
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .errors import ValidationError


DEFAULT_MAX_SELECTED = 4
DEFAULT_MAX_PROMPT_CHARS = 24_000
MAX_SKILL_BYTES = 256_000
MAX_SKILL_TREE_BYTES = 2_000_000
MAX_SKILL_TREE_FILES = 128
MAX_SKILL_TREE_ENTRIES = 512
MAX_CAPABILITY_DISCOVERY_ENTRIES = 20_000

# These are controller policy or saved operator preferences. They must not compete
# with task capabilities. Token preferences are selected once by the installer and
# injected independently by token_modes.py.
CONTROLLER_POLICY_SKILLS = {
    "uncle-matts-project-manageroo",
    "use-installed-skills-first",
}
PREFERENCE_SKILLS = {
    "caveman",
    "uncle-matts-caveman-curse",
}

_WORD = re.compile(r"[a-z0-9]+")
_EXPLICIT_ONLY = re.compile(
    r"\b(?:use\s+only\s+when|only\s+use\s+when|only\s+when)\b[^.]{0,160}\bexplicit(?:ly)?\b",
    re.IGNORECASE,
)
_INTERACTIVE_LANGUAGE = re.compile(
    r"\b(?:interview the user|interactive interview|grilling session|ask (?:the user )?questions)\b",
    re.IGNORECASE,
)
_EXTERNAL_ACTION_LANGUAGE = re.compile(
    r"\b(?:publish(?:es|ed|ing)?\s+(?:it\s+)?to\s+(?:the\s+)?(?:project\s+)?issue\s+tracker|"
    r"push(?:es|ed|ing)?(?:\s+[^.]{0,80})?\s+(?:github|gitlab|remote)|"
    r"open\s+(?:a\s+)?(?:github\s+)?pull\s+request|"
    r"create\s+(?:a\s+)?(?:github\s+|gitlab\s+)?issue|"
    r"send\s+(?:an?\s+)?(?:email|message)|publish\s+to\s+(?:social|x|twitter)|"
    r"deploy\s+to\s+(?:production|vercel|cloudflare|aws|azure|gcp)|"
    r"publish(?:es|ed|ing)?[^.]{0,100}(?:hub|issue\s+tracker|cadence|convocation|research\s+papers?)|"
    r"(?:issue|issues)[^.]{0,60}(?:project\s+)?issue\s+tracker)\b",
    re.IGNORECASE,
)
_DOLLAR_CAPABILITY_INVOCATION = re.compile(
    r"(?:^|\b(?:use|invoke|run|apply|with)\s+)\$([a-z][a-z0-9_.-]*)",
    re.IGNORECASE,
)
_DOLLAR_HYPHENATED_CAPABILITY = re.compile(r"(?<![a-z0-9_])\$([a-z][a-z0-9_.]*-[a-z0-9_.-]+)")
_NEGATED_CAPABILITY = re.compile(
    r"(?:\b(?:do\s+not|don't|never)\s+(?:use|invoke|run|apply)\s+|"
    r"\banything\s+except\s+)\$?([a-z][a-z0-9_.-]*)",
    re.IGNORECASE,
)
_NEGATED_ACTION_PREFIX = re.compile(
    r"\b(?:do\s+not|don't|never|must\s+not|should\s+not|cannot|can't|without)\b[^.;:\n]{0,100}$",
    re.IGNORECASE,
)


def _has_non_negated_match(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        clause_start = max(
            text.rfind(".", 0, match.start()),
            text.rfind(";", 0, match.start()),
            text.rfind(":", 0, match.start()),
            text.rfind("\n", 0, match.start()),
        ) + 1
        if not _NEGATED_ACTION_PREFIX.search(text[clause_start:match.start()]):
            return True
    return False


def _natural_version_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.findall(r"\d+|[^\d]+", value)
    )
_STOP_WORDS = {
    "about", "after", "again", "against", "also", "and", "any", "are", "before",
    "between", "but", "can", "complete", "current", "does", "doing", "each", "for",
    "from", "have", "into", "its", "local", "more", "not", "only", "ordinary", "other",
    "our", "should", "skill", "skills", "some", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "through", "tool", "tools", "use", "user",
    "using", "when", "where", "which", "with", "without", "work", "workflow", "you", "your",
}


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def _load_codex_config(root: Path) -> tuple[dict[str, Any], str]:
    config_path = root / "config.toml"
    if not config_path.exists():
        return ({}, "codex-config-unreadable") if config_path.is_symlink() else ({}, "")
    if not config_path.is_file():
        return {}, "codex-config-unreadable"
    try:
        with config_path.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}, "codex-config-unreadable"
    return (config, "") if isinstance(config, dict) else ({}, "codex-config-unreadable")


def _plugin_roots_from_config(root: Path, config: dict[str, Any]) -> list[Path]:
    plugins = config.get("plugins", {})
    if not isinstance(plugins, dict):
        return []
    cache = root / "plugins" / "cache"
    selected: list[Path] = []
    for plugin_id, settings in sorted(plugins.items()):
        if not isinstance(settings, dict) or not bool(settings.get("enabled", False)):
            continue
        identity = str(plugin_id).split("@", 1)
        plugin_name = identity[0].strip()
        marketplace = identity[1].strip() if len(identity) == 2 else ""
        if not plugin_name or not marketplace or not cache.is_dir():
            continue
        candidates = [
            path for path in (cache / marketplace / plugin_name).glob("*/skills")
            if path.is_dir() and not path.is_symlink()
        ]
        if not candidates:
            continue
        # Plugin caches can retain older versions. Select by the immutable version
        # directory rather than mutable filesystem timestamps.
        selected.append(max(candidates, key=lambda path: (_natural_version_key(path.parent.name), str(path))))
    return selected


def _disabled_from_config(
    root: Path,
    config: dict[str, Any],
) -> tuple[set[Path], set[str]]:
    config_path = root / "config.toml"
    skills = config.get("skills", {})
    entries = skills.get("config", []) if isinstance(skills, dict) else []
    disabled: set[Path] = set()
    disabled_names: set[str] = set()
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, dict) or item.get("enabled", True) is not False:
            continue
        name = str(item.get("name") or "").strip().casefold()
        if name:
            disabled_names.add(name)
        value = str(item.get("path") or "").strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = config_path.parent / path
        if path.name != "SKILL.md":
            path = path / "SKILL.md"
        disabled.add(path.resolve())
    return disabled, disabled_names


def _codex_host_policy(
    codex_home: Path | None = None,
) -> tuple[list[Path], set[Path], set[str], str]:
    root = (codex_home or _codex_home()).expanduser()
    config, error = _load_codex_config(root)
    disabled_paths, disabled_names = _disabled_from_config(root, config)
    return _plugin_roots_from_config(root, config), disabled_paths, disabled_names, error


def enabled_codex_plugin_skill_roots(codex_home: Path | None = None) -> list[Path]:
    return _codex_host_policy(codex_home)[0]


def codex_disabled_skill_paths(codex_home: Path | None = None) -> set[Path]:
    return _codex_host_policy(codex_home)[1]


def codex_disabled_skill_names(codex_home: Path | None = None) -> set[str]:
    return _codex_host_policy(codex_home)[2]


def default_capability_roots(source_repo: Path | None = None) -> list[Path]:
    codex_home = _codex_home()
    roots = [
        Path.home() / ".agents" / "skills",
        codex_home / "skills",
    ]
    roots.extend(enabled_codex_plugin_skill_roots(codex_home))
    if source_repo is not None:
        roots.append(source_repo.expanduser().resolve() / ".agents" / "skills")
    return roots


def _normalized_token(value: str) -> str:
    token = value.casefold()
    if len(token) > 5 and token.endswith("ing"):
        token = token[:-3]
    elif len(token) > 4 and token.endswith("ed"):
        token = token[:-2]
    elif len(token) > 4 and token.endswith("es"):
        token = token[:-2]
    elif len(token) > 3 and token.endswith("s"):
        token = token[:-1]
    return token


def _tokens(value: str) -> list[str]:
    result: list[str] = []
    for raw in _WORD.findall(value.casefold().replace("'", "")):
        if raw in _STOP_WORDS:
            continue
        token = _normalized_token(raw)
        if len(token) >= 3 and token not in _STOP_WORDS:
            result.append(token)
    return result


def _frontmatter(text: str) -> tuple[str, str, list[str], dict[str, Any]]:
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return "", "", [], {}
    lines = text.splitlines()
    try:
        end = lines.index("---", 1)
    except ValueError:
        return "", "", [], {}

    name = ""
    description = ""
    triggers: list[str] = []
    policy: dict[str, Any] = {}
    index = 1
    while index < end:
        line = lines[index]
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("'\"")
        elif line.startswith("description:"):
            value = line.split(":", 1)[1].strip()
            if value in {">", "|", ">-", "|-"}:
                parts: list[str] = []
                index += 1
                while index < end and (lines[index].startswith(" ") or not lines[index].strip()):
                    if lines[index].strip():
                        parts.append(lines[index].strip())
                    index += 1
                description = " ".join(parts)
                continue
            description = value.strip("'\"")
        elif line.startswith("triggers:"):
            index += 1
            while index < end and (lines[index].startswith(" ") or not lines[index].strip()):
                item = lines[index].strip()
                if item.startswith("-"):
                    triggers.append(item[1:].strip().strip("'\""))
                index += 1
            continue
        elif ":" in line and not line.startswith(" "):
            key, raw_value = line.split(":", 1)
            key = key.strip()
            value = raw_value.strip().strip("'\"")
            if key in {
                "mutating",
                "manageroo_interactive",
                "manageroo_external_actions",
                "manageroo_unattended_safe",
            }:
                policy[key] = value.casefold() in {"true", "yes", "1", "on"}
            elif key in {"manageroo_roles", "manageroo_sandboxes", "manageroo_required_commands"}:
                if value.startswith("[") and value.endswith("]"):
                    value = value[1:-1]
                policy[key] = [
                    part.strip().strip("'\"")
                    for part in value.split(",")
                    if part.strip().strip("'\"")
                ]
        index += 1
    return name, description, triggers, policy


def _scan_capability_roots(
    roots: list[Path],
) -> tuple[list[Path], tuple[tuple[str, int, int, int, int], ...], list[dict[str, Any]]]:
    found: list[Path] = []
    signature: list[tuple[str, int, int, int, int]] = []
    ignored: list[dict[str, Any]] = []
    scanned_entries = 0
    for unresolved in roots:
        root = unresolved.expanduser()
        try:
            root_stat = root.lstat()
        except OSError:
            continue
        signature.append((
            str(root.absolute()),
            root_stat.st_size,
            root_stat.st_mtime_ns,
            root_stat.st_ctime_ns,
            4 if root.is_symlink() else 5,
        ))
        if root.is_symlink():
            ignored.append({
                "name": "",
                "path": str(root.absolute()),
                "reason": "capability-root-symlink",
            })
            continue
        if not root.is_dir():
            continue
        resolved = root.resolve()
        for current, directory_names, file_names in os.walk(resolved, followlinks=False):
            directory_names.sort()
            file_names.sort()
            safe_directories: list[str] = []
            for name in directory_names:
                path = Path(current) / name
                scanned_entries += 1
                if scanned_entries > MAX_CAPABILITY_DISCOVERY_ENTRIES:
                    return [], tuple(sorted(signature)), [{
                        "name": "",
                        "path": str(resolved),
                        "reason": "capability-discovery-entry-limit",
                    }]
                try:
                    stat = path.lstat()
                except OSError:
                    continue
                signature.append((str(path.absolute()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, 1 if path.is_symlink() else 2))
                if path.is_symlink():
                    ignored.append({
                        "name": name,
                        "path": str((path / "SKILL.md").absolute()),
                        "reason": "symlinked-skill-directory",
                    })
                else:
                    safe_directories.append(name)
            directory_names[:] = safe_directories
            for name in file_names:
                path = Path(current) / name
                scanned_entries += 1
                if scanned_entries > MAX_CAPABILITY_DISCOVERY_ENTRIES:
                    return [], tuple(sorted(signature)), [{
                        "name": "",
                        "path": str(resolved),
                        "reason": "capability-discovery-entry-limit",
                    }]
                try:
                    stat = path.lstat()
                except OSError:
                    continue
                is_symlink = path.is_symlink()
                signature.append((str(path.absolute()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, 1 if is_symlink else 0))
                if name == "SKILL.md" and is_symlink:
                    ignored.append({
                        "name": path.parent.name,
                        "path": str(path.absolute()),
                        "reason": "symlinked-skill-entrypoint",
                    })
                if name == "SKILL.md" and not is_symlink and path.is_file():
                    found.append(path)
    return sorted(found), tuple(sorted(signature)), ignored


def _recognized_binary_support(content: bytes) -> bool:
    return (
        content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith((b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"%PDF-", b"PK\x03\x04", b"\x1f\x8b", b"ID3"))
        or (content.startswith(b"RIFF") and content[8:12] in {b"WAVE", b"WEBP"})
        or (len(content) >= 12 and content[4:8] == b"ftyp")
        or content.startswith((b"\x00\x01\x00\x00", b"OTTO", b"wOFF", b"wOF2"))
    )


def _skill_tree_digest(
    entrypoint: Path,
) -> tuple[str, list[dict[str, Any]], int, bool, bool]:
    skill_root = entrypoint.parent.resolve()
    digest = hashlib.sha256()
    files: list[dict[str, Any]] = []
    total_bytes = 0
    scanned_entries = 0
    tree_has_interactive = False
    tree_has_external_actions = False
    for current, directory_names, file_names in os.walk(skill_root, followlinks=False):
        directory_names.sort()
        file_names.sort()
        scanned_entries += len(directory_names) + len(file_names)
        if scanned_entries > MAX_SKILL_TREE_ENTRIES:
            raise ValueError("skill-tree-entry-limit")
        safe_directories: list[str] = []
        for name in directory_names:
            directory = Path(current) / name
            if directory.is_symlink():
                raise ValueError(f"symlinked-support-file:{directory}")
            safe_directories.append(name)
        directory_names[:] = safe_directories
        for name in file_names:
            path = Path(current) / name
            if path.is_symlink():
                raise ValueError(f"symlinked-support-file:{path}")
            if not path.is_file():
                continue
            if len(files) >= MAX_SKILL_TREE_FILES:
                raise ValueError("skill-tree-file-limit")
            try:
                relative = path.relative_to(skill_root).as_posix()
                size = path.stat().st_size
            except (OSError, ValueError) as exc:
                raise ValueError(f"support-file-stat:{path}") from exc
            if size < 0 or total_bytes + size > MAX_SKILL_TREE_BYTES:
                raise ValueError("skill-tree-byte-limit")
            encoded_name = relative.encode("utf-8", errors="strict")
            digest.update(len(encoded_name).to_bytes(8, "big"))
            digest.update(encoded_name)
            digest.update(size.to_bytes(8, "big"))
            file_digest = hashlib.sha256()
            read_bytes = 0
            file_content = bytearray()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(65_536)
                    if not chunk:
                        break
                    read_bytes += len(chunk)
                    if total_bytes + read_bytes > MAX_SKILL_TREE_BYTES:
                        raise ValueError("skill-tree-byte-limit")
                    digest.update(chunk)
                    file_digest.update(chunk)
                    file_content.extend(chunk)
            if read_bytes != size:
                raise ValueError(f"support-file-changed-during-read:{path}")
            total_bytes += read_bytes
            files.append({"path": relative, "bytes": read_bytes, "sha256": file_digest.hexdigest()})
            if relative != "SKILL.md":
                try:
                    support_text = bytes(file_content).decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    if not _recognized_binary_support(bytes(file_content)):
                        raise ValueError(f"invalid-utf8-support-file:{path}") from exc
                    support_text = ""
                tree_has_interactive = tree_has_interactive or _has_non_negated_match(
                    _INTERACTIVE_LANGUAGE, support_text
                )
                tree_has_external_actions = tree_has_external_actions or _has_non_negated_match(
                    _EXTERNAL_ACTION_LANGUAGE, support_text
                )
    return (
        digest.hexdigest(),
        files,
        total_bytes,
        tree_has_interactive,
        tree_has_external_actions,
    )


def _catalog(
    skill_files: list[Path],
    disabled_paths: set[Path],
    disabled_names: set[str],
    source_repo: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    ignored: list[dict[str, Any]] = []
    for path in skill_files:
        if path.resolve() in disabled_paths:
            ignored.append({"name": path.parent.name, "path": str(path.resolve()), "reason": "disabled-by-host"})
            continue
        try:
            if path.stat().st_size > MAX_SKILL_BYTES:
                ignored.append({"name": path.parent.name, "path": str(path), "reason": "entrypoint-too-large"})
                continue
            with path.open("rb") as handle:
                raw_content = handle.read(MAX_SKILL_BYTES + 1)
        except OSError:
            continue
        if len(raw_content) > MAX_SKILL_BYTES:
            ignored.append({"name": path.parent.name, "path": str(path), "reason": "entrypoint-too-large"})
            continue
        try:
            content = raw_content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            ignored.append({"name": path.parent.name, "path": str(path), "reason": "invalid-utf8"})
            continue
        name, description, triggers, policy = _frontmatter(content)
        name = (name or path.parent.name).strip()
        if not name:
            continue
        if name.casefold() in disabled_names:
            ignored.append({
                "name": name,
                "path": str(path.resolve()),
                "reason": "disabled-by-host-name",
            })
            continue
        try:
            (
                tree_sha256,
                tree_files,
                tree_bytes,
                tree_has_interactive,
                tree_has_external_actions,
            ) = _skill_tree_digest(path)
        except (OSError, ValueError) as exc:
            ignored.append({
                "name": name,
                "path": str(path.resolve()),
                "reason": str(exc) or type(exc).__name__,
            })
            continue
        instruction_content = content if content.endswith("\n") else content + "\n"
        source_kind = "host"
        if source_repo is not None:
            repository_skill_root = source_repo / ".agents" / "skills"
            try:
                path.resolve().relative_to(repository_skill_root.resolve())
                source_kind = "repository"
            except ValueError:
                pass
        if source_kind == "host" and "plugins/cache" in path.resolve().as_posix():
            source_kind = "plugin"
        by_name.setdefault(name.casefold(), []).append({
            "name": name,
            "path": str(path.resolve()),
            "description": description,
            "triggers": triggers,
            "policy": policy,
            "content": instruction_content,
            "sha256": hashlib.sha256(instruction_content.encode("utf-8", errors="strict")).hexdigest(),
            "entrypoint_sha256": hashlib.sha256(raw_content).hexdigest(),
            "tree_sha256": tree_sha256,
            "tree_files": tree_files,
            "tree_bytes": tree_bytes,
            "tree_has_interactive": tree_has_interactive,
            "tree_has_external_actions": tree_has_external_actions,
            "source_kind": source_kind,
        })
    catalog: list[dict[str, Any]] = []
    for canonical_name, copies in sorted(by_name.items()):
        display_name = copies[0]["name"]
        hashes = {item["tree_sha256"] for item in copies}
        if len(hashes) == 1:
            catalog.append(copies[0])
            if len(copies) > 1:
                ignored.extend(
                    {"name": display_name, "path": item["path"], "reason": "identical-duplicate"}
                    for item in copies[1:]
                )
            continue
        ignored.extend(
            {"name": canonical_name, "path": item["path"], "reason": "conflicting-duplicate"}
            for item in copies
        )
    return catalog, ignored


class CapabilityIndex:
    """Run-local capability catalog that refreshes when an entrypoint changes."""

    def __init__(
        self,
        roots: list[Path] | None = None,
        *,
        disabled_paths: set[Path] | None = None,
        disabled_names: set[str] | None = None,
        source_repo: Path | None = None,
    ) -> None:
        self.source_repo = source_repo.expanduser().resolve() if source_repo is not None else None
        self._root_override = list(roots) if roots is not None else None
        self._disabled_path_override = disabled_paths
        self._disabled_name_override = disabled_names
        self.roots: list[Path] = []
        self.disabled_paths: set[Path] = set()
        self.disabled_names: set[str] = set()
        self.host_policy_error = ""
        self._refresh_host_policy()
        self._signature: tuple[tuple[str, int, int, int, int], ...] | None = None
        self._cached: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None
        self._lock = threading.Lock()

    def _refresh_host_policy(self) -> None:
        codex_home = _codex_home()
        plugin_roots, host_disabled_paths, host_disabled_names, policy_error = _codex_host_policy(
            codex_home
        )
        selected_roots = (
            list(self._root_override)
            if self._root_override is not None
            else [Path.home() / ".agents" / "skills", codex_home / "skills", *plugin_roots]
        )
        if self.source_repo is not None:
            selected_roots.append(self.source_repo / ".agents" / "skills")
        self.roots = list(dict.fromkeys(
            path.expanduser().absolute() for path in selected_roots
        ))
        path_values = (
            self._disabled_path_override
            if self._disabled_path_override is not None
            else host_disabled_paths
        )
        name_values = (
            self._disabled_name_override
            if self._disabled_name_override is not None
            else host_disabled_names
        )
        self.disabled_paths = {path.expanduser().resolve() for path in path_values}
        self.disabled_names = {
            name.strip().casefold() for name in name_values if name.strip()
        }
        self.host_policy_error = policy_error

    def _policy_signature(self) -> tuple[tuple[str, int, int, int, int], ...]:
        values = [f"root:{path}" for path in self.roots]
        values.extend(f"disabled-path:{path}" for path in sorted(self.disabled_paths))
        values.extend(f"disabled-name:{name}" for name in sorted(self.disabled_names))
        if self.host_policy_error:
            values.append(f"host-policy-error:{self.host_policy_error}")
        return tuple((value, 0, 0, 0, 3) for value in sorted(values))

    def load(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self._lock:
            self._refresh_host_policy()
            skill_files, filesystem_signature, discovery_ignored = _scan_capability_roots(self.roots)
            discovery_signature = tuple(
                (
                    f"ignored:{item.get('reason', '')}:{item.get('path', '')}",
                    0,
                    0,
                    0,
                    6,
                )
                for item in discovery_ignored
            )
            signature = tuple(sorted((
                *filesystem_signature,
                *discovery_signature,
                *self._policy_signature(),
            )))
            if self._cached is None or signature != self._signature:
                fatal_discovery = any(
                    item.get("reason") in {
                        "capability-discovery-entry-limit",
                        "capability-root-symlink",
                    }
                    for item in discovery_ignored
                )
                if fatal_discovery:
                    self._cached = ([], discovery_ignored)
                else:
                    catalog, catalog_ignored = _catalog(
                        skill_files,
                        self.disabled_paths,
                        self.disabled_names,
                        self.source_repo,
                    )
                    self._cached = (catalog, [*catalog_ignored, *discovery_ignored])
                self._signature = signature
            return self._cached


def _fuzzy_matches(query_terms: set[str], skill_terms: set[str]) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    unmatched_query = [term for term in query_terms - skill_terms if len(term) >= 5]
    unmatched_skill = [term for term in skill_terms - query_terms if len(term) >= 5]
    for query_term in unmatched_query:
        best = ""
        ratio = 0.0
        for skill_term in unmatched_skill:
            current = SequenceMatcher(None, query_term, skill_term).ratio()
            if current > ratio:
                best, ratio = skill_term, current
        if best and ratio >= 0.84:
            matches.append((query_term, best))
    return matches


def _explicit_requested_names(query_text: str) -> set[str]:
    requested = {
        value.rstrip(".,;:!?").casefold()
        for value in _DOLLAR_CAPABILITY_INVOCATION.findall(query_text)
        if not value.isupper()
    }
    requested.update(
        value.rstrip(".,;:!?").casefold()
        for value in _DOLLAR_HYPHENATED_CAPABILITY.findall(query_text)
    )
    return requested


def _negated_capability_names(query_text: str) -> set[str]:
    return {
        value.rstrip(".,;:!?").casefold()
        for value in _NEGATED_CAPABILITY.findall(query_text)
    }


def _explicitly_names(name: str, query_text: str, requested_names: set[str]) -> bool:
    normalized_name = name.casefold()
    natural_name = " ".join(_WORD.findall(normalized_name.replace("-", " ")))
    lowered_query = query_text.casefold()
    natural_invocation = re.search(
        rf"\b(?:use|invoke|run|apply|go\s+get)\s+(?:the\s+)?{re.escape(natural_name)}\b",
        lowered_query,
    )
    starts_with_name = len(_tokens(name)) >= 3 and (
        lowered_query.startswith(natural_name + " ") or lowered_query == natural_name
    )
    return normalized_name in requested_names or (
        bool(natural_name)
        and (natural_invocation is not None or starts_with_name)
    )


def _incompatibility(item: dict[str, Any], *, role: str, sandbox: str) -> str:
    policy = item.get("policy", {}) if isinstance(item.get("policy"), dict) else {}
    if bool(item.get("tree_has_interactive")) or bool(
        policy.get("manageroo_interactive")
    ) or _has_non_negated_match(
        _INTERACTIVE_LANGUAGE,
        " ".join([item["description"], item.get("content", "")])
    ):
        return "interactive"
    roles = {str(value).casefold() for value in policy.get("manageroo_roles", [])}
    if roles and role.casefold() not in roles:
        return "role"
    sandboxes = {str(value).casefold() for value in policy.get("manageroo_sandboxes", [])}
    if sandboxes and sandbox.casefold() not in sandboxes:
        return "sandbox"
    if bool(policy.get("mutating")) and sandbox == "read-only":
        return "requires-write"
    if bool(policy.get("manageroo_external_actions")) or bool(
        item.get("tree_has_external_actions")
    ):
        return "external-actions"
    if _has_non_negated_match(
        _EXTERNAL_ACTION_LANGUAGE,
        " ".join([
            item["name"],
            item["description"],
            *item.get("triggers", []),
            item.get("content", ""),
        ])
    ):
        return "external-actions"
    for command in policy.get("manageroo_required_commands", []):
        command_name = str(command).strip()
        if command_name and shutil.which(command_name) is None:
            return f"missing-command:{command_name}"
    return ""


def route_capabilities(
    task: str,
    *,
    focus: str = "",
    roots: list[Path] | None = None,
    role: str = "",
    sandbox: str = "read-only",
    repo: Path | None = None,
    max_selected: int = DEFAULT_MAX_SELECTED,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    disabled_paths: set[Path] | None = None,
    disabled_names: set[str] | None = None,
    index: CapabilityIndex | None = None,
) -> dict[str, Any]:
    if max_selected < 0:
        raise ValueError("max_selected must be zero or greater")
    if max_prompt_chars < 0:
        raise ValueError("max_prompt_chars must be zero or greater")
    capability_index = index or CapabilityIndex(
        roots,
        disabled_paths=disabled_paths,
        disabled_names=disabled_names,
        source_repo=repo,
    )
    catalog, ignored = capability_index.load()
    selected_roots = capability_index.roots
    # Absolute paths contain usernames, organization names, and repository words that
    # can accidentally overpower the operator's intent. Repository identity is recorded
    # for audit, but never treated as free routing keywords.
    query_text = " ".join(part for part in (task, role) if part).strip()
    query_terms = set(_tokens(query_text))
    ordered_query_terms = _tokens(task)
    focus_text = " ".join(str(focus).split())[:12_000]
    focus_terms = set(_tokens(focus_text))

    excluded_preferences = [item for item in catalog if item["name"].casefold() in PREFERENCE_SKILLS]
    excluded_policies = [item for item in catalog if item["name"].casefold() in CONTROLLER_POLICY_SKILLS]
    candidates = [
        item for item in catalog
        if item["name"].casefold() not in PREFERENCE_SKILLS | CONTROLLER_POLICY_SKILLS
    ]
    document_frequency: Counter[str] = Counter()
    candidate_terms: dict[str, set[str]] = {}
    for item in candidates:
        terms = set(_tokens(" ".join([item["name"], item["description"], *item["triggers"]])))
        candidate_terms[item["path"]] = terms
        document_frequency.update(terms)

    lowered_query = query_text.casefold()
    negated_names = _negated_capability_names(query_text)
    explicitly_requested = _explicit_requested_names(query_text) - negated_names
    ranked: list[dict[str, Any]] = []
    incompatible: list[dict[str, Any]] = []
    blocking_errors: list[str] = []
    if capability_index.host_policy_error:
        blocking_errors.append("capability-host-config-unreadable")
    ignored_by_name: dict[str, set[str]] = {}
    for ignored_item in ignored:
        ignored_by_name.setdefault(str(ignored_item.get("name", "")).casefold(), set()).add(
            str(ignored_item.get("reason", ""))
        )
    if "capability-discovery-entry-limit" in {
        reason for reasons in ignored_by_name.values() for reason in reasons
    } or any(item.get("reason") == "capability-discovery-entry-limit" for item in ignored):
        blocking_errors.append("capability-catalog-overflow")
    if any(item.get("reason") == "capability-root-symlink" for item in ignored):
        blocking_errors.append("capability-catalog-unsafe-root")
    if any(
        item.get("reason") in {"symlinked-skill-directory", "symlinked-skill-entrypoint"}
        for item in ignored
    ):
        blocking_errors.append("capability-catalog-unsafe-symlink")
    for name, reasons in ignored_by_name.items():
        if not name or not _explicitly_names(name, query_text, explicitly_requested):
            continue
        if "conflicting-duplicate" in reasons:
            blocking_errors.append(f"explicit-capability-conflicting-duplicate:{name}")
        if "disabled-by-host" in reasons or "disabled-by-host-name" in reasons:
            blocking_errors.append(f"explicit-capability-disabled:{name}")
        for reason in sorted(reasons - {
            "conflicting-duplicate",
            "disabled-by-host",
            "disabled-by-host-name",
            "identical-duplicate",
        }):
            reason_code = reason.split(":", 1)[0]
            blocking_errors.append(f"explicit-capability-unavailable:{name}:{reason_code}")
    known_names = (
        {item["name"].casefold() for item in catalog}
        | set(ignored_by_name)
        | CONTROLLER_POLICY_SKILLS
        | PREFERENCE_SKILLS
    )
    for requested_name in sorted(explicitly_requested):
        if requested_name not in known_names:
            blocking_errors.append(f"explicit-capability-not-found:{requested_name}")
    total_documents = max(1, len(candidates))
    for item in candidates:
        if item["name"].casefold() in negated_names:
            continue
        terms = candidate_terms[item["path"]]
        overlap = sorted(query_terms & terms)
        weighted_overlap = sum(
            1.0 + math.log((1.0 + total_documents) / (1.0 + document_frequency[term]))
            for term in overlap
        )
        fuzzy = _fuzzy_matches(query_terms, terms)
        focus_overlap = sorted(focus_terms & terms)
        name_terms = set(_tokens(item["name"]))
        explicit = _explicitly_names(item["name"], query_text, explicitly_requested)
        explicit_only = _EXPLICIT_ONLY.search(item["description"]) is not None
        if explicit_only and not explicit:
            continue
        incompatibility = _incompatibility(item, role=role, sandbox=sandbox)
        if incompatibility:
            incompatible.append({
                "name": item["name"],
                "path": item["path"],
                "reason": incompatibility,
                "explicit": explicit,
            })
            if explicit:
                blocking_errors.append(
                    f"explicit-capability-incompatible:{item['name']}:{incompatibility}"
                )
            continue
        name_overlap = query_terms & name_terms
        fuzzy_name = _fuzzy_matches(query_terms, name_terms)
        name_match = len(name_terms) >= 2 and name_overlap == name_terms
        single_name_lead = (
            len(name_terms) == 1
            and bool(ordered_query_terms)
            and ordered_query_terms[0] in name_terms
        )
        fuzzy_name_match = len(name_terms) == 1 and bool(fuzzy_name)
        trigger_matches: list[str] = []
        for trigger in item["triggers"]:
            trigger_terms = set(_tokens(trigger))
            if not trigger_terms:
                continue
            trigger_phrase = " ".join(_WORD.findall(trigger.casefold()))
            coverage = len(query_terms & trigger_terms) / len(trigger_terms)
            if len(trigger_terms) >= 2 and (trigger_phrase in lowered_query or coverage >= 0.75):
                trigger_matches.append(trigger)
        qualifies = bool(
            explicit
            or trigger_matches
            or name_match
            or single_name_lead
            or fuzzy_name_match
            or len(overlap) >= 3
        )
        score = (
            weighted_overlap
            + (2.0 * len(name_overlap))
            + (1.5 * len(fuzzy_name))
            + (0.5 * len(fuzzy))
            + (8.0 * len(trigger_matches))
            + (4.0 * len(focus_overlap))
        )
        if explicit:
            score += 100.0
        if not qualifies or score < 2.0:
            continue
        reasons: list[str] = []
        if explicit:
            reasons.append("request names this capability")
        if overlap:
            reasons.append("matched intent: " + ", ".join(overlap[:8]))
        if trigger_matches:
            reasons.append("matched trigger: " + ", ".join(trigger_matches[:4]))
        if fuzzy:
            reasons.append(
                "matched spelling variants: "
                + ", ".join(f"{left}->{right}" for left, right in fuzzy[:4])
            )
        if focus_overlap:
            reasons.append("task focus: " + ", ".join(focus_overlap[:8]))
        ranked.append({
            **item,
            "activation": "explicit-only" if explicit_only else "automatic",
            "explicit": explicit,
            "score": round(score, 3),
            "reasons": reasons,
        })

    ranked.sort(key=lambda item: (-float(item["score"]), item["name"], item["path"]))
    chosen: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    used_chars = 0
    for item in ranked:
        content_chars = len(item["content"])
        public = {**item, "content_chars": content_chars}
        if len(chosen) >= max_selected:
            omitted.append({**public, "reason": "selection-limit"})
            if item.get("explicit"):
                blocking_errors.append("explicit-capability-selection-limit")
            continue
        if used_chars + content_chars > max_prompt_chars:
            omitted.append({**public, "reason": "prompt-budget"})
            if item.get("explicit"):
                blocking_errors.append("explicit-capability-prompt-budget")
            continue
        chosen.append(public)
        used_chars += content_chars

    effective_capabilities = [
        {
            "name": item["name"],
            "path": item["path"],
            "sha256": item["sha256"],
            "tree_sha256": item["tree_sha256"],
        }
        for item in chosen
    ]
    effective_sha256 = hashlib.sha256(
        json.dumps(
            effective_capabilities,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    ).hexdigest()

    return {
        "ok": not blocking_errors,
        "automatic": True,
        "user_selection_required": False,
        "role": role,
        "sandbox": sandbox,
        "repo": str(repo.resolve()) if repo is not None else "",
        "roots": [str(path) for path in selected_roots],
        "query_sha256": hashlib.sha256(query_text.encode("utf-8", errors="surrogateescape")).hexdigest(),
        "focus_sha256": hashlib.sha256(focus_text.encode("utf-8", errors="surrogateescape")).hexdigest(),
        "catalog_count": len(catalog),
        "catalog_paths": sorted(
            {item["path"] for item in catalog}
            | {item["path"] for item in ignored if item.get("path")}
        ),
        "catalog_entries": [
            {"name": name, "path": path}
            for name, path in sorted({
                (str(item.get("name", "")).casefold(), str(item.get("path", "")))
                for item in [*catalog, *ignored]
                if str(item.get("name", "")).strip() and str(item.get("path", "")).strip()
            })
        ],
        "candidate_count": len(ranked),
        "selected": chosen,
        "omitted": omitted,
        "excluded_preferences": excluded_preferences,
        "excluded_controller_policies": excluded_policies,
        "ignored": ignored,
        "incompatible": incompatible,
        "max_selected": max_selected,
        "max_prompt_chars": max_prompt_chars,
        "selected_prompt_chars": used_chars,
        "blocking_errors": sorted(set(blocking_errors)),
        "effective_capabilities": effective_capabilities,
        "effective_sha256": effective_sha256,
    }


def validate_capability_route_freshness(route: dict[str, Any]) -> None:
    """Fail before worker launch if any selected capability tree changed."""
    for item in route.get("selected", []):
        path = Path(str(item.get("path", "")))
        expected = str(item.get("tree_sha256", ""))
        try:
            actual, _, _, _, _ = _skill_tree_digest(path)
        except (OSError, ValueError) as exc:
            raise ValidationError(
                f"Selected capability became unreadable after routing: {path}: {exc}"
            ) from exc
        if not expected or actual != expected:
            raise ValidationError(f"Selected capability changed after routing: {path}")


def capability_route_record(route: dict[str, Any]) -> dict[str, Any]:
    def scrub(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{key: value for key, value in item.items() if key != "content"} for item in items]

    return {
        **route,
        "selected": scrub(list(route.get("selected", []))),
        "omitted": scrub(list(route.get("omitted", []))),
        "excluded_preferences": scrub(list(route.get("excluded_preferences", []))),
        "excluded_controller_policies": scrub(list(route.get("excluded_controller_policies", []))),
    }


def render_capability_prompt(route: dict[str, Any]) -> str:
    selected = list(route.get("selected", []))
    if not selected:
        return ""
    lines = [
        "# Automatically selected capabilities",
        "",
        "Manageroo selected these capabilities automatically from the assignment. Do not ask the operator which skill or tool to use. Apply the relevant instructions without broadening scope. The controller packet, current repository truth, and role restrictions win over conflicting capability text.",
    ]
    for item in selected:
        lines.extend(
            [
                "",
                f"## {item['name']}",
                f"Source: {item['path']}",
                "",
                "<skill_instructions>",
                str(item["content"]).rstrip(),
                "</skill_instructions>",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def format_capability_route(route: dict[str, Any]) -> str:
    lines = [
        "AUTOMATIC CAPABILITY ROUTE",
        f"Installed capabilities indexed: {route.get('catalog_count', 0)}",
        f"Selected for this job: {len(route.get('selected', []))}",
        "Operator skill selection required: no",
    ]
    selected = list(route.get("selected", []))
    if not selected:
        lines.append("No specialist capability matched strongly enough; Manageroo uses its normal controller process.")
    for item in selected:
        reason = "; ".join(item.get("reasons", [])) or "highest deterministic match"
        lines.append(f"- {item['name']}: {reason}")
    conflicts = [item for item in route.get("ignored", []) if item.get("reason") == "conflicting-duplicate"]
    if conflicts:
        lines.append(f"Conflicting duplicate copies skipped: {len(conflicts)}")
    if route.get("blocking_errors"):
        lines.append("Blocked: " + ", ".join(route["blocking_errors"]))
    return "\n".join(lines) + "\n"
