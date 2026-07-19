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
TURTLE_ASCII = "<[====]o"
BTTLABS_LABEL = "bttlabs.fun"
BTTLABS_URL = "https://bttlabs.fun"

_RESET = "\033[0m"
_BOLD = "\033[1m"
_ITALIC = "\033[3m"
_UNDERLINE = "\033[4m"
_COLORS = (
    "\033[38;5;51m",
    "\033[38;5;45m",
    "\033[38;5;81m",
    "\033[38;5;141m",
    "\033[38;5;213m",
    "\033[38;5;208m",
    "\033[38;5;220m",
)

_MAX_BOX_WIDTH = 96
_MIN_FULL_BANNER_COLUMNS = 68


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


def _terminal_columns(stream: TextIO) -> int:
    """Return real terminal width without borrowing another terminal's dimensions."""

    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return _MAX_BOX_WIDTH + 2
    try:
        return max(1, os.get_terminal_size(fd).columns)
    except OSError:
        return _MAX_BOX_WIDTH + 2


def _banner_box_width(stream: TextIO) -> int:
    columns = _terminal_columns(stream)
    # Leave two terminal columns unused so the right border never reaches the
    # automatic-wrap boundary used by many terminal emulators.
    return max(1, min(_MAX_BOX_WIDTH, columns - 4))


def _box_line(text: str = "", *, width: int, align: str = "left") -> str:
    content = text.center(width) if align == "center" else f" {text}".ljust(width)
    return f"║{content[:width]}║"


def _manageroo_art(width: int):
    return (
        f"╔{'═' * width}╗",
        ("scan_box", "MANAGEROO", "center"),
        ("wave_box", "Uncle Matt's Project Manageroo", "left"),
        ("rainbow_box", THINKING_LINE),
        ("turtle_box", TURTLE_ASCII, "left"),
        ("link_box", BTTLABS_LABEL, "center"),
        f"╚{'═' * width}╝",
    )


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


def _effect_content(text: str, kind: str, offset: int, features: TerminalFeatures) -> str:
    if kind == "rainbow_box":
        return _rainbow_italic(text, offset, features)
    if not features.color:
        return text
    if kind == "link_box":
        parts = [_BOLD, _UNDERLINE]
    else:
        parts = [_BOLD if kind == "scan_box" else ""]
    visible_index = 0
    for char in text:
        if char.isspace():
            parts.append(char)
            continue
        if kind == "scan_box":
            scan = offset % max(1, sum(1 for item in text if not item.isspace()))
            distance = abs(visible_index - scan)
            color = (
                "\033[38;5;220m"
                if distance == 0
                else "\033[38;5;81m"
                if distance == 1
                else "\033[38;5;51m"
            )
        elif kind == "turtle_box":
            color = "\033[38;5;118m" if visible_index % 2 else "\033[38;5;46m"
        elif kind == "link_box":
            color = _COLORS[(offset + visible_index * 2) % len(_COLORS)]
        else:
            color = _COLORS[(visible_index + offset) % len(_COLORS)]
        parts.append(color)
        parts.append(char)
        visible_index += 1
    parts.append(_RESET)
    return "".join(parts)


def _terminal_hyperlink(label: str, url: str, features: TerminalFeatures, offset: int) -> str:
    colored = _effect_content(label, "link_box", offset, features)
    if not features.color:
        return label
    return f"\033]8;;{url}\033\\{colored}\033]8;;\033\\"


def _effect_box_line(
    text: str,
    kind: str,
    offset: int,
    features: TerminalFeatures,
    *,
    width: int,
    align: str = "left",
) -> str:
    if not features.color:
        if kind == "link_box":
            return _box_line(text, width=width, align="center")
        return _box_line(text, width=width, align=align)
    if kind == "turtle_box":
        travel = max(0, width - len(TURTLE_ASCII) - 1)
        position = offset % (travel + 1)
        content = f" {' ' * position}{TURTLE_ASCII}".ljust(width)
        return f"║{_effect_content(content[:width], kind, offset, features)}║"
    if kind == "link_box":
        label = _terminal_hyperlink(BTTLABS_LABEL, BTTLABS_URL, features, offset)
        left = max(0, (width - len(BTTLABS_LABEL)) // 2)
        right = max(0, width - len(BTTLABS_LABEL) - left)
        return f"║{' ' * left}{label}{' ' * right}║"
    content = text.center(width) if align == "center" else f" {text}".ljust(width)
    return f"║{_effect_content(content[:width], kind, offset, features)}║"


def _write_effect_box_line(
    stream: TextIO,
    text: str,
    kind: str,
    features: TerminalFeatures,
    *,
    width: int,
    delay: float,
    animate: bool,
    align: str = "left",
) -> None:
    if not animate:
        stream.write(
            _effect_box_line(text, kind, 0, features, width=width, align=align) + "\n"
        )
        stream.flush()
        return
    for offset in range(len(_COLORS) * 3):
        stream.write(
            "\r" + _effect_box_line(text, kind, offset, features, width=width, align=align)
        )
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
    persistent_rainbow: bool = False,
) -> None:
    """Print a resize-safe banner.

    `persistent_rainbow` remains accepted for installer/API compatibility, but
    Manageroo intentionally no longer runs a background cursor-positioning ticker.
    A ticker painted to fixed screen rows corrupts normal terminal scrollback when
    output scrolls or the window is resized. The banner now animates once, freezes,
    and then behaves like ordinary terminal output.
    """

    del persistent_rainbow
    features = terminal_features(stream, animation=animation)
    columns = _terminal_columns(stream)
    use_compact = compact or (features.color and columns < _MIN_FULL_BANNER_COLUMNS)
    width = _banner_box_width(stream)

    if use_compact:
        lines = (
            f"⚡ {FULL_NAME}",
            f"   command: {PUBLIC_COMMAND} · acronym: {FULL_ACRONYM}",
            f"   {TAGLINE}",
        )
    else:
        lines = ("", *_manageroo_art(width), "")

    for index, line in enumerate(lines):
        if isinstance(line, tuple) and line[0].endswith("_box"):
            kind = line[0]
            text = line[1]
            align = line[2] if len(line) > 2 else "left"
            _write_effect_box_line(
                stream,
                text,
                kind,
                features,
                width=width,
                delay=delay,
                animate=features.animation,
                align=align,
            )
            continue
        stream.write(_paint(line, index, features) + "\n")
        stream.flush()
        if features.animation and delay > 0:
            time.sleep(delay)
    return None


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
