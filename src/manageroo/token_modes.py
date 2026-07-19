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

# Everything shipped in the source distribution. These assets remain available for
# explicit installation/import, but Manageroo does not claim ownership of equivalent
# skills already present in a user's host environment.
BUNDLED_SKILL_LIBRARY = {
    "uncle-matts-project-manageroo": "skills/uncle-matts-project-manageroo/SKILL.md",
    "use-installed-skills-first": "skills/use-installed-skills-first/SKILL.md",
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
    "academic-verify": "skills/academic-verify/SKILL.md",
    "data-research": "skills/data-research/SKILL.md",
    "perplexity-research": "skills/perplexity-research/SKILL.md",
    "repo-architecture": "skills/repo-architecture/SKILL.md",
    "find-skills": "skills/find-skills/SKILL.md",
    "write-a-skill": "skills/write-a-skill/SKILL.md",
    "edit-skill": "skills/edit-skill/SKILL.md",
    "skillify": "skills/skillify/SKILL.md",
    "skillpack-check": "skills/skillpack-check/SKILL.md",
    "handoff": "skills/handoff/SKILL.md",
    "to-prd": "skills/to-prd/SKILL.md",
    "to-issues": "skills/to-issues/SKILL.md",
    "grill-me": "skills/grill-me/SKILL.md",
    "grill-with-docs": "skills/grill-with-docs/SKILL.md",
    "functional-area-resolver": "skills/functional-area-resolver/SKILL.md",
    "diagnose": "skills/diagnose/SKILL.md",
    "tdd": "skills/tdd/SKILL.md",
    "testing": "skills/testing/SKILL.md",
    "improve-codebase-architecture": "skills/improve-codebase-architecture/SKILL.md",
    "security-review": "skills/security-review/SKILL.md",
    "cross-modal-review": "skills/cross-modal-review/SKILL.md",
    "subagent-orchestrator": "skills/subagent-orchestrator/SKILL.md",
    "minion-orchestrator": "skills/minion-orchestrator/SKILL.md",
    "autoreview": "skills/autoreview/SKILL.md",
    "plain-web-copy": "skills/plain-web-copy/SKILL.md",
    "fix-my-bad-website": "skills/fix-my-bad-website/SKILL.md",
    "web-design-guidelines": "skills/web-design-guidelines/SKILL.md",
    "open-design": "skills/open-design/SKILL.md",
    "playwright": "skills/playwright/SKILL.md",
    "playwright-interactive": "skills/playwright-interactive/SKILL.md",
    "caveman": "skills/caveman/SKILL.md",
    "uncle-matts-caveman-curse": "skills/uncle-matts-caveman-curse/SKILL.md",
}

# Portable public default. These skills define Manageroo's own operating contract.
# Host-specific research, design, memory, marketplace, and competing-orchestrator
# skills are deliberately not installed by default.
CORE_SKILL_NAMES = (
    "uncle-matts-project-manageroo",
    "use-installed-skills-first",
    "pimp-my-prompt",
    "to-prd",
    "to-issues",
    "grill-me",
    "grill-with-docs",
    "diagnose",
    "tdd",
    "testing",
    "security-review",
    "handoff",
    "write-a-skill",
    "edit-skill",
    "skillify",
    "caveman",
    "uncle-matts-caveman-curse",
)
CORE_SKILL_PACK = {name: BUNDLED_SKILL_LIBRARY[name] for name in CORE_SKILL_NAMES}
OPTIONAL_SKILL_PACK = {
    name: asset
    for name, asset in BUNDLED_SKILL_LIBRARY.items()
    if name not in CORE_SKILL_PACK
}

# Backward-compatible names used by installer/reconcile code. "Recommended" now
# means the small portable core, not every asset shipped in the repository.
RECOMMENDED_SKILL_PACK = CORE_SKILL_PACK
CORE_HELPER_SKILLS = CORE_SKILL_PACK

ALIASES = {
    "none": "off",
    "normal": "off",
    "clean": "caveman",
}
