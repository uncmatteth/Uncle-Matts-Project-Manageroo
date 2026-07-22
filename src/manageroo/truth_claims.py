from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


BANNED_PUBLIC_CLAIMS = (
    "full vision support",
    "real vision support",
    "understands screenshots",
    "understands images",
    "guaranteed production ready",
    "one-button production deploy",
    "autonomous production deploy",
    "real subagent swarm",
    "parallel implementation branches",
    "ai can fix autoreview findings",
    "ai can fix clawpatch findings",
    "silently self-improves",
)

_DENIAL_RE = re.compile(
    r"\b(?:does\s+not|do\s+not|cannot|can\s+not|never|must\s+not|is\s+not|are\s+not|no|without|instead\s+of)\b",
    re.IGNORECASE,
)
_CLAUSE_BREAK_RE = re.compile(r";|\b(?:but|however|although|though|yet)\b|,\s*(?:and|but)\b", re.IGNORECASE)


def sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
        if sentence.strip()
    ]


def claim_is_explicitly_denied(sentence: str, phrase: str) -> bool:
    """Return true only when a denial in the same governing clause precedes the claim.

    A random earlier `no`, `not`, or `without` is not enough. Clause separators after the
    denial break its authority over the prohibited phrase, so text such as
    `No setup is required; Manageroo has full vision support` is still rejected.
    """
    lowered = sentence.casefold()
    target = phrase.casefold()
    index = lowered.find(target)
    if index < 0:
        return False
    before = lowered[:index]
    matches = list(_DENIAL_RE.finditer(before))
    if not matches:
        return False
    denial = matches[-1]
    governed = before[denial.end() :]
    if _CLAUSE_BREAK_RE.search(governed):
        return False
    # Keep the relation local. This is intentionally conservative: public copy can always
    # use a clearer explicit denial rather than relying on a distant grammatical dependency.
    words = re.findall(r"[a-z0-9'-]+", governed)
    return len(words) <= 10


def public_overclaim_violations(paths: Iterable[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for sentence in sentences(text):
            for phrase in BANNED_PUBLIC_CLAIMS:
                if phrase in sentence.casefold() and not claim_is_explicitly_denied(sentence, phrase):
                    violations.append(f"{path}:{phrase}:{sentence[:240]}")
    return violations
