from __future__ import annotations

import re
import struct
from pathlib import Path

from .util import sha256_file


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif"}
PDF_SUFFIXES = {".pdf"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
DESIGN_SUFFIXES = {".fig", ".sketch", ".psd", ".ai", ".indd"}
PROSE_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc", ".org"}


def looks_binary(path: Path) -> bool:
    try:
        data = path.read_bytes()[:8192]
    except OSError:
        return True
    return b"\0" in data


def content_kind_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES | PDF_SUFFIXES | AUDIO_SUFFIXES | VIDEO_SUFFIXES | DESIGN_SUFFIXES:
        return "media"
    if suffix in PROSE_SUFFIXES:
        return "prose"
    return "source"


def language_for_media(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in PDF_SUFFIXES:
        return "pdf"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in DESIGN_SUFFIXES:
        return "design"
    return None


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            return None
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            return None
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += length
    return None


def image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            data = handle.read(512 * 1024)
    except OSError:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        if data[12:16] == b"VP8X":
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return width, height
    return None


def pdf_page_count(path: Path) -> int | None:
    try:
        with path.open("rb") as handle:
            text = handle.read(8 * 1024 * 1024).decode("latin-1", errors="ignore")
    except OSError:
        return None
    matches = re.findall(r"/Type\s*/Page\b", text)
    return len(matches) or None


def text_summary(path: Path, relative: str = "") -> tuple[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    headings = [
        line.strip()
        for line in lines
        if line.strip().startswith("#") or re.match(r"^[A-Z0-9][A-Za-z0-9 ,:'\"()/-]{2,120}$", line.strip())
    ][:20]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(stripped)
        if len(" ".join(current)) > 300:
            paragraphs.append(" ".join(current))
            current = []
        if len(paragraphs) >= 6:
            break
    if current and len(paragraphs) < 6:
        paragraphs.append(" ".join(current))

    summary_lines = [
        "Generated file summary.",
        f"Path: {relative or path.name}",
        f"Bytes: {path.stat().st_size}",
        f"Lines: {len(lines)}",
        f"SHA-256: {sha256_file(path)}",
    ]
    if headings:
        summary_lines.append("Headings or prose anchors:")
        summary_lines.extend(f"- {item[:180]}" for item in headings)
    if paragraphs:
        summary_lines.append("Opening prose excerpts:")
        summary_lines.extend(f"- {item[:300]}" for item in paragraphs)
    return "\n".join(summary_lines), len(lines)


def media_summary(path: Path, relative: str = "") -> tuple[str, int]:
    suffix = path.suffix.lower()
    language = language_for_media(path) or "binary"
    details = []
    if language == "image":
        dimensions = image_dimensions(path)
        if dimensions:
            details.append(f"dimensions={dimensions[0]}x{dimensions[1]}")
    elif language == "pdf":
        pages = pdf_page_count(path)
        if pages:
            details.append(f"approx_pages={pages}")
    detail = ", ".join(details) if details else "content not decoded by local metadata reader"
    return (
        "\n".join(
            [
                "Generated media summary.",
                f"Path: {relative or path.name}",
                f"Media type: {language}",
                f"Suffix: {suffix or '(none)'}",
                f"Bytes: {path.stat().st_size}",
                f"Details: {detail}",
                f"SHA-256: {sha256_file(path)}",
                "Note: this is metadata for agent context, not OCR or vision interpretation.",
            ]
        ),
        1,
    )


def summary_for_context(path: Path, relative: str = "") -> tuple[str, int]:
    if content_kind_for_path(path) == "media":
        return media_summary(path, relative)
    return text_summary(path, relative)
