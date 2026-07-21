from __future__ import annotations

import re
from collections.abc import Iterable


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE_SPLIT_RE = re.compile(r"[;,.!?]\s*")
_DENIAL_NEAR_END_RE = re.compile(
    r"(?:\b(?:does|do|did|is|are|was|were|can|could|must|will|would|should)\s+not\b"
    r"|\bcannot\b|\bnever\b|\bmust\s+not\b|\bno\b|\bwithout\b|\binstead\s+of\b)"
    r"[^;,.!?]{0,80}$",
    re.IGNORECASE,
)


def sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(text) if sentence.strip()]


def claim_is_explicitly_denied(sentence: str, phrase: str) -> bool:
    """Return true only when a denial in the same clause actually governs the claim phrase."""
    lowered = sentence.casefold()
    needle = phrase.casefold()
    index = lowered.find(needle)
    if index < 0:
        return False
    before = lowered[:index]
    clause_before = _CLAUSE_SPLIT_RE.split(before)[-1]
    return bool(_DENIAL_NEAR_END_RE.search(clause_before))


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
