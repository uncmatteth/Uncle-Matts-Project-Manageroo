from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .managed_contract_common import (
    EXECUTION_INTENT_MUTATING,
    EXECUTION_INTENT_READ_ONLY,
)


_ACKNOWLEDGMENT_RE = re.compile(
    r"^\s*(?:ok(?:ay)?|thanks?|thank\s+you|cool|got\s+it|sounds\s+good|"
    r"perfect|yep|yes|continue|go\s+ahead|resume)\s*[.!]*\s*$",
    re.IGNORECASE,
)
_EXPLICIT_READ_ONLY_RE = re.compile(
    r"\b(?:do\s+not|don't|never)\s+(?:change|edit|modify|write|touch|apply)"
    r"(?:\s+(?:anything|it|the\s+(?:code|files?|project|repo(?:sitory)?|source|workspace)|"
    r"this\s+(?:project|repo(?:sitory)?|workspace)))?\s*(?=[.!?]|$)|"
    r"\bwithout\s+(?:changing|editing|modifying)\s+"
    r"(?:anything|it|the\s+(?:code|files?|project|repo(?:sitory)?|source|workspace)|"
    r"this\s+(?:project|repo(?:sitory)?|workspace))\b|"
    r"\b(?:no\s+edits?|read[- ]only|"
    r"review\s+only|audit\s+only|just\s+(?:review|audit|inspect|analy[sz]e|tell\s+me)|"
    r"tell\s+me\s+(?:what(?:'s|\s+is)?\s+wrong|the\s+issues?))\b",
    re.IGNORECASE,
)
_READ_ONLY_WORK_RE = re.compile(
    r"\b(?:review|audit|inspect|analy[sz]e|investigate|diagnose|assess|explain)\b",
    re.IGNORECASE,
)
_MUTATING_WORK_RE = re.compile(
    r"\b(?:fix|finish|restore|rescue|update|refactor|implement|change|edit|write|"
    r"create|copy|move|rename|delete|remove|run|build|install|publish|ship|deploy|"
    r"commit|push|make|repair|apply)\b",
    re.IGNORECASE,
)
_REPOSITORY_NAME_RE = re.compile(
    r"\b(?:repo(?:sitory)?|project)\s+(?:named\s+)?[`\"']?([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_PATH_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/][^\s\"'`]+|/(?:[^\s\"'`]+))"
)
_EVIDENCE_PATH_PREFIX_RE = re.compile(
    r"\b(?:(?:pasted|attached|saved)\s+)?(?:artifact|error|evidence|handoff|"
    r"logs?|output|report|trace)\s*:\s*$",
    re.IGNORECASE,
)
_TRAILING_EVIDENCE_FILE_PREFIX_RE = re.compile(
    r"\b(?:from|read|review|see|then|using)\s*$", re.IGNORECASE
)
_EVIDENCE_FILE_SUFFIXES = frozenset(
    {".json", ".jsonl", ".log", ".md", ".out", ".txt", ".yaml", ".yml"}
)
_REPOSITORY_NAME_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "but",
        "for",
        "going",
        "is",
        "of",
        "on",
        "the",
        "this",
        "to",
        "with",
        "without",
    }
)
_GENERIC_PROJECT_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "on",
        "project",
        "repo",
        "repository",
        "the",
        "this",
    }
)


def _project_words(value: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", value.casefold())
        if word not in _GENERIC_PROJECT_WORDS
    }


def _discover_project_records() -> list[dict[str, Any]]:
    from .projects import discover_projects

    report = discover_projects(limit=0, agent="auto")
    return [item for item in report.get("projects", []) if isinstance(item, dict)]


def _git_directory_valid(git_dir: Path) -> bool:
    if not (git_dir / "HEAD").is_file():
        return False
    if (git_dir / "objects").is_dir():
        return True
    try:
        common_value = (git_dir / "commondir").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return False
    common = Path(common_value).expanduser()
    if not common.is_absolute():
        common = git_dir / common
    return (common.resolve(strict=False) / "objects").is_dir()


def _repo_for_path(path: Path, continuity_module: Any) -> Path | None:
    candidate = path.expanduser().resolve(strict=False)
    start = candidate if candidate.is_dir() else candidate.parent
    root = continuity_module._git_root(start)
    if root is None:
        return None
    marker = root / ".git"
    if marker.is_symlink():
        return None
    if marker.is_dir():
        return root if _git_directory_valid(marker) else None
    if marker.is_file():
        try:
            prefix, value = marker.read_text(encoding="utf-8").strip().split(":", 1)
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if prefix.casefold() != "gitdir":
            return None
        git_dir = Path(value.strip()).expanduser()
        if not git_dir.is_absolute():
            git_dir = marker.parent / git_dir
        git_dir = git_dir.resolve(strict=False)
        return root if _git_directory_valid(git_dir) else None
    return None


def _path_is_contextual(prompt: str, match: re.Match[str], continuity_module: Any) -> bool:
    if continuity_module._span_is_quoted(prompt, match.start(), match.end()):
        return True
    prefix, clause = continuity_module._path_clause(
        prompt, match.start(), match.end()
    )
    if _EVIDENCE_PATH_PREFIX_RE.search(prefix):
        return True
    raw = match.group(0).rstrip(".,;:!?)]}>")
    if (
        Path(raw).suffix.casefold() in _EVIDENCE_FILE_SUFFIXES
        and _TRAILING_EVIDENCE_FILE_PREFIX_RE.search(prefix)
    ):
        return True
    return bool(
        continuity_module._HISTORICAL_CONTEXT.search(clause)
        and not continuity_module._CURRENT_PATH_DIRECTIVE.search(clause)
    )


def _repository_identity_prompt(prompt: str, continuity_module: Any) -> str:
    characters = list(prompt)
    for match in _PATH_TOKEN_RE.finditer(prompt):
        if _path_is_contextual(prompt, match, continuity_module):
            characters[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(characters)


def _explicit_path_repositories(
    prompt: str, *, cwd: Path, continuity_module: Any
) -> list[Path]:
    repositories: list[Path] = []
    for match in _PATH_TOKEN_RE.finditer(prompt):
        if _path_is_contextual(prompt, match, continuity_module):
            continue
        raw = match.group(0).rstrip(".,;:!?)]}>")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        repo = _repo_for_path(candidate, continuity_module)
        if repo is not None and repo not in repositories:
            repositories.append(repo)
    return repositories


def _project_matches(
    prompt: str,
    projects: list[dict[str, Any]],
    *,
    allow_fuzzy: bool = False,
) -> list[Path]:
    text = prompt.casefold()
    request_words = _project_words(prompt)
    exact: list[Path] = []
    scored: list[tuple[int, Path]] = []
    for project in projects:
        name = str(project.get("name") or "").strip()
        raw_path = str(project.get("path") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path).expanduser().resolve(strict=False)
        if (name and name.casefold() in text) or raw_path.casefold() in text:
            exact.append(path)
        scored.append((len(request_words & _project_words(name)), path))
    if exact:
        return sorted(set(exact), key=str)
    if not allow_fuzzy:
        return []
    best = max((score for score, _ in scored), default=0)
    if best <= 0:
        return []
    return sorted({path for score, path in scored if score == best}, key=str)


def _resolve_repository_binding(
    *,
    prompt: str,
    cwd: str,
    previous_bound_repo: str = "",
    projects: list[dict[str, Any]] | None = None,
    continuity_module: Any,
) -> dict[str, Any]:
    current = Path(cwd or ".").expanduser().resolve(strict=False)
    explicit_paths = _explicit_path_repositories(
        prompt, cwd=current, continuity_module=continuity_module
    )
    if len(explicit_paths) == 1:
        selected = explicit_paths[0]
        if previous_bound_repo and selected != Path(previous_bound_repo).resolve(strict=False):
            return {
                "status": "conflict",
                "repo": previous_bound_repo,
                "source": "explicit-path",
                "candidates": [str(selected)],
                "detail": "Changing repositories requires replacing the active request.",
            }
        return {
            "status": "bound",
            "repo": str(selected),
            "source": "explicit-path",
            "candidates": [str(selected)],
        }
    if len(explicit_paths) > 1:
        return {
            "status": "ambiguous",
            "repo": "",
            "source": "explicit-path",
            "candidates": [str(item) for item in explicit_paths],
        }

    discovered = (
        list(projects)
        if projects is not None
        else _discover_project_records()
        if current.exists()
        else []
    )
    identity_prompt = _repository_identity_prompt(prompt, continuity_module)
    named_repo_token = _REPOSITORY_NAME_RE.search(identity_prompt)
    if (
        named_repo_token
        and named_repo_token.group(1).casefold() in _REPOSITORY_NAME_STOPWORDS
    ):
        named_repo_token = None
    named_matches = _project_matches(
        identity_prompt,
        discovered,
        allow_fuzzy=named_repo_token is not None,
    )
    explicit_project_identity = bool(named_matches or named_repo_token)
    if len(named_matches) == 1:
        selected = named_matches[0]
        if previous_bound_repo and selected != Path(previous_bound_repo).resolve(strict=False):
            return {
                "status": "conflict",
                "repo": previous_bound_repo,
                "source": "explicit-project-name",
                "candidates": [str(selected)],
                "detail": "Changing repositories requires replacing the active request.",
            }
        return {
            "status": "bound",
            "repo": str(selected),
            "source": "explicit-project-name",
            "candidates": [str(selected)],
        }
    if len(named_matches) > 1:
        return {
            "status": "ambiguous",
            "repo": "",
            "source": "explicit-project-name",
            "candidates": [str(item) for item in named_matches],
        }
    if named_repo_token:
        return {
            "status": "missing",
            "repo": "",
            "source": "explicit-project-name",
            "candidates": [],
            "detail": (
                "The explicitly named repository was not found; Manageroo will not substitute "
                "another registered project."
            ),
        }

    if previous_bound_repo:
        previous = Path(previous_bound_repo).expanduser().resolve(strict=False)
        if _repo_for_path(previous, continuity_module) is not None:
            return {
                "status": "bound",
                "repo": str(previous),
                "source": "active-request",
                "candidates": [str(previous)],
            }

    current_repo = _repo_for_path(current, continuity_module)
    if current_repo is not None:
        return {
            "status": "bound",
            "repo": str(current_repo),
            "source": "current-git-root",
            "candidates": [str(current_repo)],
        }

    if not explicit_project_identity and len(discovered) == 1:
        selected = Path(str(discovered[0].get("path") or "")).expanduser().resolve(
            strict=False
        )
        return {
            "status": "bound",
            "repo": str(selected),
            "source": "sole-discovered-project",
            "candidates": [str(selected)],
        }
    return {
        "status": "ambiguous" if len(discovered) > 1 else "missing",
        "repo": "",
        "source": "project-discovery",
        "candidates": [str(item.get("path") or "") for item in discovered if item.get("path")],
    }


def _execution_intent(text: str) -> str:
    if _EXPLICIT_READ_ONLY_RE.search(text):
        return EXECUTION_INTENT_READ_ONLY
    mutating = bool(_MUTATING_WORK_RE.search(text))
    read_only = bool(_READ_ONLY_WORK_RE.search(text))
    if read_only and not mutating:
        return EXECUTION_INTENT_READ_ONLY
    return EXECUTION_INTENT_MUTATING


def _is_acknowledgment(prompt: str) -> bool:
    return bool(_ACKNOWLEDGMENT_RE.fullmatch(prompt.strip()))


def _effective_request_text(state: dict[str, Any]) -> str:
    return "\n\n".join(
        str(item.get("text") or "").strip()
        for item in state.get("messages", [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    )


def _requires_managed_run(prompt: str, continuity_module: Any) -> bool:
    text = prompt.strip()
    if not text or continuity_module._PAUSE_REQUEST.search(text) or _is_acknowledgment(text):
        return False
    actionable = bool(
        continuity_module._CLEAR_WORK_REQUEST.search(text)
        or continuity_module._CLEAR_WORK_AFTER_PREAMBLE.search(text)
        or continuity_module._DIRECT_WORK_QUESTION.search(text)
        or _READ_ONLY_WORK_RE.search(text)
    )
    return actionable
