from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import TextIO

PRODUCT_NAME = "Uncle Matt's Project Manageroo"
FULL_NAME = PRODUCT_NAME
FULL_ACRONYM = "MANAGEROO"
PUBLIC_COMMAND = "manageroo"
PROJECT_DIR = ".manageroo"
TAGLINE = "ONE BRIEF IN. CHECKED PATCH OUT."
THINKING_LINE = "Offload your thinking so you can really do some thinking..."

_RESET = "\033[0m"
_BOLD = "\033[1m"
_ITALIC = "\033[3m"
_COLORS = (
    "\033[38;5;51m",
    "\033[38;5;45m",
    "\033[38;5;81m",
    "\033[38;5;141m",
    "\033[38;5;213m",
    "\033[38;5;208m",
    "\033[38;5;220m",
)


_BOX_WIDTH = 96


def _box_line(text: str = "", *, align: str = "left") -> str:
    content = text.center(_BOX_WIDTH) if align == "center" else f" {text}".ljust(_BOX_WIDTH)
    return f"║{content[:_BOX_WIDTH]}║"


_MANAGEROO_ART = (
    f"╔{'═' * _BOX_WIDTH}╗",
    _box_line("MANAGEROO", align="center"),
    _box_line("Uncle Matt's Project Manageroo"),
    f"╚{'═' * _BOX_WIDTH}╝",
)


@dataclass(frozen=True)
class TerminalFeatures:
    color: bool
    animation: bool


def terminal_features(
    stream: TextIO = sys.stdout,
    *,
    animation: bool | None = None,
) -> TerminalFeatures:
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    color = is_tty and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
    auto_animation = (
        color
        and not os.environ.get("CI")
        and os.environ.get("MANAGEROO_ANIMATION", "1").lower()
        not in {"0", "false", "no", "off"}
    )
    enabled = auto_animation if animation is None else animation and color
    return TerminalFeatures(color=color, animation=enabled)


def _paint(text: str, index: int, features: TerminalFeatures) -> str:
    if not features.color:
        return text
    return f"{_BOLD}{_COLORS[index % len(_COLORS)]}{text}{_RESET}"


def _rainbow_italic(text: str, offset: int, features: TerminalFeatures) -> str:
    if not features.color:
        return text
    parts = [_ITALIC]
    color_index = offset
    for char in text:
        if char.isspace():
            parts.append(char)
            continue
        parts.append(_COLORS[color_index % len(_COLORS)])
        parts.append(char)
        color_index += 1
    parts.append(_RESET)
    return "".join(parts)


def _write_rainbow_line(
    stream: TextIO,
    text: str,
    features: TerminalFeatures,
    *,
    delay: float,
) -> None:
    if not features.animation:
        stream.write(_rainbow_italic(text, 0, features) + "\n")
        stream.flush()
        return
    for offset in range(len(_COLORS) * 3):
        stream.write("\r" + _rainbow_italic(text, offset, features))
        stream.flush()
        if delay > 0:
            time.sleep(delay)
    stream.write("\n")
    stream.flush()


def print_banner(
    stream: TextIO = sys.stdout,
    *,
    animation: bool | None = None,
    delay: float = 0.018,
    compact: bool = False,
) -> None:
    features = terminal_features(stream, animation=animation)
    if compact:
        lines = (
            f"⚡ {FULL_NAME}",
            f"   command: {PUBLIC_COMMAND} · acronym: {FULL_ACRONYM}",
            f"   {TAGLINE}",
        )
    else:
        lines = (
            "",
            *_MANAGEROO_ART,
            ("rainbow", f"  {THINKING_LINE}"),
            f"  {FULL_NAME.upper()}",
            f"  COMMAND: {PUBLIC_COMMAND}   ACRONYM: {FULL_ACRONYM}",
            f"  {TAGLINE}",
            "",
        )
    for index, line in enumerate(lines):
        if isinstance(line, tuple) and line[0] == "rainbow":
            _write_rainbow_line(stream, line[1], features, delay=delay)
            continue
        stream.write(_paint(line, index, features) + "\n")
        stream.flush()
        if features.animation and delay > 0:
            time.sleep(delay)


def status_line(
    label: str,
    detail: str = "",
    *,
    ok: bool | None = None,
    stream: TextIO = sys.stdout,
) -> None:
    features = terminal_features(stream, animation=False)
    marker = "✓" if ok is True else "✗" if ok is False else "◆"
    text = f"{marker} {label}"
    if detail:
        text += f" — {detail}"
    stream.write(_paint(text, 2 if ok is not False else 5, features) + "\n")
    stream.flush()
