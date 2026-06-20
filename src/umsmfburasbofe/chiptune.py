from __future__ import annotations

import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 22_050

_NOTE_OFFSETS = {
    "C": 0,
    "C#": 1,
    "D": 2,
    "D#": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "G": 7,
    "G#": 8,
    "A": 9,
    "A#": 10,
    "B": 11,
}


def note_frequency(note: str) -> float:
    if note in {"-", "R", "REST"}:
        return 0.0
    name = note[:-1]
    octave = int(note[-1])
    midi = 12 * (octave + 1) + _NOTE_OFFSETS[name]
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _square(phase: float, duty: float = 0.5) -> float:
    return 1.0 if phase % 1.0 < duty else -1.0


def _triangle(phase: float) -> float:
    return 4.0 * abs((phase % 1.0) - 0.5) - 1.0


def _envelope(position: float) -> float:
    attack = min(1.0, position / 0.06) if position < 0.06 else 1.0
    release = min(1.0, (1.0 - position) / 0.12) if position > 0.88 else 1.0
    return max(0.0, min(attack, release))


def _patterns(cue: str) -> tuple[list[str], list[str], int, int]:
    if cue == "success":
        melody = [
            "E5", "G5", "B5", "E6", "D6", "B5", "G5", "B5",
            "F#5", "A5", "C#6", "F#6", "E6", "C#6", "A5", "C#6",
            "G5", "B5", "D6", "G6", "F#6", "D6", "B5", "D6",
            "A5", "C6", "E6", "A6", "G6", "E6", "B5", "E6",
        ]
        bass = ["E2"] * 8 + ["F#2"] * 8 + ["G2"] * 8 + ["A2"] * 4 + ["B2"] * 4
        return melody, bass, 172, 1
    if cue == "build":
        melody = [
            "E5", "-", "E5", "G5", "A5", "-", "B5", "A5",
            "G5", "E5", "D5", "E5", "G5", "-", "A5", "B5",
            "C6", "B5", "A5", "G5", "E5", "G5", "A5", "-",
            "B5", "D6", "C6", "B5", "A5", "G5", "E5", "-",
        ]
        bass = ["E2"] * 8 + ["C2"] * 8 + ["G2"] * 8 + ["D2"] * 8
        return melody, bass, 156, 3
    melody = [
        "E5", "G5", "A5", "B5", "A5", "G5", "E5", "D5",
        "E5", "G5", "B5", "D6", "B5", "A5", "G5", "E5",
        "F#5", "A5", "B5", "C#6", "B5", "A5", "F#5", "E5",
        "G5", "B5", "D6", "E6", "D6", "B5", "A5", "G5",
    ]
    bass = ["E2"] * 8 + ["G2"] * 8 + ["F#2"] * 8 + ["G2"] * 4 + ["B2"] * 4
    return melody, bass, 148, 3


def generate_theme(path: Path, *, cue: str = "install", variant: int = 0) -> Path:
    """Generate an original Atari/NES-inspired WAV using only the Python standard library."""
    melody, bass, bpm, repeats = _patterns(cue)
    rng = random.Random(0xB77 + variant + sum(ord(ch) for ch in cue))
    seconds_per_step = 60.0 / bpm / 2.0
    total_steps = len(melody) * repeats
    total_samples = int(total_steps * seconds_per_step * SAMPLE_RATE)
    frames = bytearray()

    for sample_index in range(total_samples):
        elapsed = sample_index / SAMPLE_RATE
        step_float = elapsed / seconds_per_step
        step_index = int(step_float)
        in_step = step_float - step_index
        pattern_index = step_index % len(melody)

        lead_freq = note_frequency(melody[pattern_index])
        bass_freq = note_frequency(bass[pattern_index % len(bass)])
        env = _envelope(in_step)
        lead = _square(elapsed * lead_freq, 0.25) * env if lead_freq else 0.0
        harmony = _square(elapsed * (lead_freq / 2.0), 0.5) * env if lead_freq else 0.0
        low = _triangle(elapsed * bass_freq) * (0.72 + 0.28 * env) if bass_freq else 0.0

        beat = step_index % 8
        noise = 0.0
        if in_step < 0.12 and beat in {0, 4}:
            noise = (rng.random() * 2.0 - 1.0) * (1.0 - in_step / 0.12)
        elif in_step < 0.07 and beat in {2, 6}:
            noise = (1.0 if rng.random() > 0.5 else -1.0) * 0.35

        pulse = math.sin(2.0 * math.pi * 55.0 * elapsed) * max(0.0, 1.0 - in_step * 12.0)
        mixed = 0.43 * lead + 0.13 * harmony + 0.26 * low + 0.10 * noise + 0.08 * pulse
        sample = int(max(-1.0, min(1.0, mixed)) * 32767)
        frames.extend(struct.pack("<h", sample))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(bytes(frames))
    return path


def _player_command(path: Path) -> list[str] | None:
    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay", str(path)]
    for executable, args in (
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
        ("mpv", ["--no-video", "--really-quiet"]),
        ("paplay", []),
        ("aplay", ["-q"]),
    ):
        if shutil.which(executable):
            return [executable, *args, str(path)]
    if os.name == "nt":
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell:
            escaped = str(path).replace("'", "''")
            return [
                powershell,
                "-NoProfile",
                "-Command",
                f"$p=New-Object System.Media.SoundPlayer '{escaped}'; $p.PlaySync()",
            ]
    return None


@dataclass
class ThemePlayback:
    cue: str = "install"
    enabled: bool = True
    variant: int = 0
    process: subprocess.Popen[bytes] | None = None
    path: Path | None = None

    def start(self) -> bool:
        disabled = os.environ.get("UMSMFBURASBOFE_MUSIC", "1").lower() in {
            "0",
            "false",
            "no",
            "off",
        }
        if not self.enabled or disabled or os.environ.get("CI") or not sys.stdout.isatty():
            return False
        temp_root = Path(tempfile.mkdtemp(prefix="umsmfburasbofe-music-"))
        self.path = generate_theme(temp_root / f"{self.cue}.wav", cue=self.cue, variant=self.variant)
        command = _player_command(self.path)
        if not command:
            return False
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        return True

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.path:
            try:
                shutil.rmtree(self.path.parent)
            except OSError:
                pass

    def __enter__(self) -> "ThemePlayback":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()


def play_once(*, cue: str = "install", variant: int = 0) -> bool:
    playback = ThemePlayback(cue=cue, enabled=True, variant=variant)
    if not playback.start():
        playback.stop()
        return False
    if playback.process:
        playback.process.wait()
    playback.stop()
    return True
