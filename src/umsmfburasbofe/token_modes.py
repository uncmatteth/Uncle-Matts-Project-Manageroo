from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assets import asset_path


@dataclass(frozen=True)
class TokenMode:
    id: str
    label: str
    skill_name: str | None
    asset: str | None
    prompt: str


TOKEN_MODES = {
    "off": TokenMode(
        id="off",
        label="Off",
        skill_name=None,
        asset=None,
        prompt="",
    ),
    "caveman": TokenMode(
        id="caveman",
        label="Token Reduction: Caveman",
        skill_name="caveman",
        asset="skills/caveman/SKILL.md",
        prompt=(
            "Token mode: Caveman. Be terse. Drop filler, pleasantries, hedging, "
            "and needless connector words. Keep exact technical meaning, code, "
            "commands, JSON keys, quoted errors, paths, and safety warnings intact."
        ),
    ),
    "curse": TokenMode(
        id="curse",
        label="Token Reduction: Uncle Matt's Caveman Curse",
        skill_name="uncle-matts-caveman-curse",
        asset="skills/uncle-matts-caveman-curse/SKILL.md",
        prompt=(
            "Token mode: Uncle Matt's Caveman Curse. Use caveman compression with "
            "blunt profanity in natural-language status, findings, and explanations "
            "when it fits because life is more fun with appropriately placed, "
            "well-used profanity. Curse at broken code or broken process, not the user. "
            "Never add profanity to code, shell commands, JSON keys, exact errors, "
            "quoted source, or user-facing product copy unless explicitly asked."
        ),
    ),
}

RECOMMENDED_SKILL_PACK = {
    "uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition": (
        "skills/uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition/SKILL.md"
    ),
    "pimp-my-prompt": "skills/pimp-my-prompt/SKILL.md",
    "brain-ops": "skills/brain-ops/SKILL.md",
    "query": "skills/query/SKILL.md",
    "ingest": "skills/ingest/SKILL.md",
    "idea-ingest": "skills/idea-ingest/SKILL.md",
    "media-ingest": "skills/media-ingest/SKILL.md",
    "voice-note-ingest": "skills/voice-note-ingest/SKILL.md",
    "article-enrichment": "skills/article-enrichment/SKILL.md",
    "book-mirror": "skills/book-mirror/SKILL.md",
    "strategic-reading": "skills/strategic-reading/SKILL.md",
    "pdf": "skills/pdf/SKILL.md",
    "brain-pdf": "skills/brain-pdf/SKILL.md",
    "citation-fixer": "skills/citation-fixer/SKILL.md",
    "reports": "skills/reports/SKILL.md",
    "exact-text-replacement": "skills/exact-text-replacement/SKILL.md",
    "write-a-skill": "skills/write-a-skill/SKILL.md",
    "edit-skill": "skills/edit-skill/SKILL.md",
    "skillify": "skills/skillify/SKILL.md",
    "diagnose": "skills/diagnose/SKILL.md",
    "tdd": "skills/tdd/SKILL.md",
    "autoreview": "skills/autoreview/SKILL.md",
    "plain-web-copy": "skills/plain-web-copy/SKILL.md",
    "fix-my-bad-website": "skills/fix-my-bad-website/SKILL.md",
    "caveman": "skills/caveman/SKILL.md",
    "uncle-matts-caveman-curse": "skills/uncle-matts-caveman-curse/SKILL.md",
}
CORE_HELPER_SKILLS = RECOMMENDED_SKILL_PACK

ALIASES = {
    "none": "off",
    "normal": "off",
    "clean": "caveman",
    "uncle": "curse",
    "uncle-matts-caveman-curse": "curse",
    "caveman-curse": "curse",
}


def normalize_mode(mode: str) -> str:
    normalized = ALIASES.get(mode.strip().lower(), mode.strip().lower())
    if normalized not in TOKEN_MODES:
        allowed = ", ".join(sorted(TOKEN_MODES))
        raise ValueError(f"Unknown token mode {mode!r}. Use one of: {allowed}.")
    return normalized


def token_mode_state_path() -> Path:
    explicit = os.environ.get("UMSMFBURASBOFE_TOKEN_MODE_FILE")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".config" / "umsmfburasbofe" / "token-mode.json"


def token_mode_skills_dir() -> Path:
    explicit = os.environ.get("UMSMFBURASBOFE_SKILLS_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".agents" / "skills"


def _backup_path(destination: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = destination.with_name(f"{destination.name}.umsmfburasbofe-backup-{stamp}")
    index = 2
    while candidate.exists():
        candidate = destination.with_name(
            f"{destination.name}.umsmfburasbofe-backup-{stamp}-{index}"
        )
        index += 1
    return candidate


def _install_bundled_skill(root: Path, skill_name: str, asset: str) -> str:
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    root_real = root.resolve()
    skill_dir = root / skill_name
    if skill_dir.is_symlink():
        raise ValueError(f"Refusing to install through symlinked skill directory: {skill_dir}")
    if skill_dir.exists() and not skill_dir.is_dir():
        raise ValueError(f"Refusing to install over non-directory skill path: {skill_dir}")
    skill_dir.mkdir(parents=True, exist_ok=True)
    if not skill_dir.resolve().is_relative_to(root_real):
        raise ValueError(f"Refusing to install skill outside skills root: {skill_dir}")
    destination = root / skill_name / "SKILL.md"
    if destination.is_symlink():
        raise ValueError(f"Refusing to overwrite symlinked skill file: {destination}")
    source = asset_path(asset)
    if destination.exists() and destination.read_bytes() != source.read_bytes():
        shutil.copy2(destination, _backup_path(destination))
    shutil.copy2(source, destination)
    return str(destination)


def install_core_helper_skills(skills_dir: Path | None = None) -> dict[str, str]:
    root = (skills_dir or token_mode_skills_dir()).expanduser().resolve()
    return {
        skill_name: _install_bundled_skill(root, skill_name, asset)
        for skill_name, asset in RECOMMENDED_SKILL_PACK.items()
    }


def install_token_skills(skills_dir: Path | None = None) -> dict[str, str]:
    root = (skills_dir or token_mode_skills_dir()).expanduser().resolve()
    installed: dict[str, str] = {}
    for mode in TOKEN_MODES.values():
        if not mode.skill_name or not mode.asset:
            continue
        installed[mode.id] = _install_bundled_skill(root, mode.skill_name, mode.asset)
    return installed


def read_token_mode(state_path: Path | None = None) -> dict[str, Any]:
    path = (state_path or token_mode_state_path()).expanduser()
    if not path.exists():
        return {
            "mode": "off",
            "label": TOKEN_MODES["off"].label,
            "state_path": str(path),
            "skills_dir": str(token_mode_skills_dir()),
            "installed_skills": {},
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    mode = normalize_mode(str(data.get("mode", "off")))
    data["mode"] = mode
    data["label"] = TOKEN_MODES[mode].label
    data.setdefault("state_path", str(path))
    data.setdefault("skills_dir", str(token_mode_skills_dir()))
    data.setdefault("installed_skills", {})
    return data


def set_token_mode(
    mode: str,
    *,
    state_path: Path | None = None,
    skills_dir: Path | None = None,
    install_skills: bool = True,
) -> dict[str, Any]:
    normalized = normalize_mode(mode)
    installed = install_token_skills(skills_dir) if install_skills and normalized != "off" else {}
    path = (state_path or token_mode_state_path()).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "mode": normalized,
        "label": TOKEN_MODES[normalized].label,
        "selected_skill": TOKEN_MODES[normalized].skill_name,
        "state_path": str(path),
        "skills_dir": str((skills_dir or token_mode_skills_dir()).expanduser().resolve()),
        "installed_skills": installed,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def token_mode_prompt(mode: str | None = None) -> str:
    selected = normalize_mode(mode) if mode is not None else read_token_mode()["mode"]
    prompt = TOKEN_MODES[selected].prompt
    if not prompt:
        return ""
    return "# Token reduction mode\n\n" + prompt
