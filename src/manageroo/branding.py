from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Sequence
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


_BOX_WIDTH = 96


def _box_line(text: str = "", *, align: str = "left") -> str:
    content = text.center(_BOX_WIDTH) if align == "center" else f" {text}".ljust(_BOX_WIDTH)
    return f"║{content[:_BOX_WIDTH]}║"


_MANAGEROO_ART = (
    f"╔{'═' * _BOX_WIDTH}╗",
    ("scan_box", "MANAGEROO", "center"),
    ("wave_box", "Uncle Matt's Project Manageroo", "left"),
    ("rainbow_box", THINKING_LINE),
    ("turtle_box", TURTLE_ASCII, "left"),
    ("link_box", BTTLABS_LABEL, "center"),
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
            color = "\033[38;5;220m" if distance == 0 else "\033[38;5;81m" if distance == 1 else "\033[38;5;51m"
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
    align: str = "left",
) -> str:
    if not features.color:
        if kind == "link_box":
            return _box_line(text, align="center")
        return _box_line(text, align=align)
    if kind == "turtle_box":
        travel = max(0, _BOX_WIDTH - len(TURTLE_ASCII) - 1)
        position = offset % (travel + 1)
        content = f" {' ' * position}{TURTLE_ASCII}".ljust(_BOX_WIDTH)
        return f"║{_effect_content(content[:_BOX_WIDTH], kind, offset, features)}║"
    if kind == "link_box":
        label = _terminal_hyperlink(BTTLABS_LABEL, BTTLABS_URL, features, offset)
        left = max(0, (_BOX_WIDTH - len(BTTLABS_LABEL)) // 2)
        right = max(0, _BOX_WIDTH - len(BTTLABS_LABEL) - left)
        return f"║{' ' * left}{label}{' ' * right}║"
    content = text.center(_BOX_WIDTH) if align == "center" else f" {text}".ljust(_BOX_WIDTH)
    return f"║{_effect_content(content[:_BOX_WIDTH], kind, offset, features)}║"


def _write_effect_box_line(
    stream: TextIO,
    text: str,
    kind: str,
    features: TerminalFeatures,
    *,
    delay: float,
    animate: bool,
    align: str = "left",
) -> None:
    if not animate:
        stream.write(_effect_box_line(text, kind, 0, features, align=align) + "\n")
        stream.flush()
        return
    for offset in range(len(_COLORS) * 3):
        stream.write("\r" + _effect_box_line(text, kind, offset, features, align=align))
        stream.flush()
        if delay > 0:
            time.sleep(delay)
    stream.write("\n")
    stream.flush()


class BannerTicker:
    def __init__(
        self,
        stream: TextIO,
        rows: Sequence[tuple[int, str, str, str]],
        features: TerminalFeatures,
        interval: float = 0.12,
    ) -> None:
        self.stream = stream
        self.rows = tuple(rows)
        self.features = features
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="manageroo-rainbow-banner", daemon=True)

    def start(self) -> "BannerTicker":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=0.5)

    def _run(self) -> None:
        offset = 0
        while not self._stop.wait(self.interval):
            try:
                self.stream.write("\033[s")
                for row, kind, text, align in self.rows:
                    self.stream.write(
                        f"\033[{row};1H"
                        f"{_effect_box_line(text, kind, offset, self.features, align=align)}"
                    )
                self.stream.write("\033[u")
                self.stream.flush()
            except OSError:
                self._stop.set()
                return
            offset += 1


def _current_terminal_row() -> int | None:
    if os.name == "nt":
        return None
    try:
        import re
        import select
        import termios
        import tty

        with open("/dev/tty", "r+b", buffering=0) as terminal:
            fd = terminal.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                terminal.write(b"\033[6n")
                response = bytearray()
                deadline = time.monotonic() + 0.2
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([terminal], [], [], 0.02)
                    if not ready:
                        continue
                    chunk = terminal.read(1)
                    if not chunk:
                        break
                    response.extend(chunk)
                    if chunk == b"R":
                        break
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (OSError, ValueError):
        return None
    match = re.search(rb"\x1b\[(\d+);(\d+)R", bytes(response))
    if not match:
        return None
    return int(match.group(1))


def print_banner(
    stream: TextIO = sys.stdout,
    *,
    animation: bool | None = None,
    delay: float = 0.018,
    compact: bool = False,
    persistent_rainbow: bool = False,
) -> BannerTicker | None:
    features = terminal_features(stream, animation=animation)
    effect_lines: list[tuple[int, str, str, str]] = []
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
            "",
        )
    for index, line in enumerate(lines):
        if isinstance(line, tuple) and line[0].endswith("_box"):
            kind = line[0]
            text = line[1]
            align = line[2] if len(line) > 2 else "left"
            effect_lines.append((index, kind, text, align))
            _write_effect_box_line(
                stream,
                text,
                kind,
                features,
                delay=delay,
                animate=features.animation and not persistent_rainbow,
                align=align,
            )
            continue
        stream.write(_paint(line, index, features) + "\n")
        stream.flush()
        if features.animation and delay > 0:
            time.sleep(delay)
    if persistent_rainbow and features.animation and effect_lines:
        current_row = _current_terminal_row()
        if current_row is not None:
            rows = []
            for index, kind, text, align in effect_lines:
                row = current_row - (len(lines) - index)
                if row > 0:
                    rows.append((row, kind, text, align))
            if rows:
                return BannerTicker(stream, rows, features).start()
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
