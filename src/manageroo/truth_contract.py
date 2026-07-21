from __future__ import annotations

import re
from collections.abc import Iterable


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE_SPLIT_RE = re.compile(r"[;,.!?]\s*")
_DENIAL_SUFFIX_PATTERNS = (
    re.compile(
        r"\b(?:does|do|did|is|are|was|were|can|could|must|will|would|should)\s+not"
        r"(?:\s+[a-z0-9_-]+){0,4}\s+$",
        re.IGNORECASE,
    ),
    re.compile(r"\bcannot(?:\s+[a-z0-9_-]+){0,4}\s+$", re.IGNORECASE),
    re.compile(r"\bnever(?:\s+[a-z0-9_-]+){0,4}\s+$", re.IGNORECASE),
    # `no` and `without` must directly govern the prohibited capability. Broad
    # windows such as "no setup for <claim>" are affirmative capability claims.
    re.compile(r"\bno\s+$", re.IGNORECASE),
    re.compile(r"\bwithout\s+$", re.IGNORECASE),
    re.compile(r"\binstead\s+of\s+$", re.IGNORECASE),
)


def sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(text) if sentence.strip()]


def _occurrence_is_denied(sentence: str, phrase: str, index: int) -> bool:
    before = sentence.casefold()[:index]
    clause_before = _CLAUSE_SPLIT_RE.split(before)[-1]
    return any(pattern.search(clause_before) for pattern in _DENIAL_SUFFIX_PATTERNS)


def claim_is_explicitly_denied(sentence: str, phrase: str) -> bool:
    """Return true only when every occurrence of a prohibited claim is explicitly denied."""
    lowered = sentence.casefold()
    needle = phrase.casefold()
    if not needle:
        return False
    indexes = [match.start() for match in re.finditer(re.escape(needle), lowered)]
    return bool(indexes) and all(_occurrence_is_denied(sentence, phrase, index) for index in indexes)


def find_overclaim_offenders(text: str, banned_phrases: Iterable[str]) -> list[dict[str, str]]:
    offenders: list[dict[str, str]] = []
    for sentence in sentences(text):
        lowered = sentence.casefold()
        for phrase in banned_phrases:
            if phrase.casefold() not in lowered:
                continue
            if claim_is_explicitly_denied(sentence, phrase):
                continue
            offenders.append({"phrase": phrase, "sentence": sentence})
    return offenders
