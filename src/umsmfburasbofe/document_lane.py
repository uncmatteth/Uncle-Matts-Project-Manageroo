from __future__ import annotations

from typing import Any


DOCUMENT_RULES = [
    {
        "id": "brain-source-first",
        "rule": "If a brain page exists, treat it as the source of truth; PDFs are renderings.",
    },
    {
        "id": "exact-text-protected",
        "rule": "Exact user-provided text must not be paraphrased, normalized, or polished unless asked.",
    },
    {
        "id": "tiny-prose-batches",
        "rule": "Long prose work should use one chapter, one section, or one tiny batch at a time.",
    },
    {
        "id": "do-not-read-ahead",
        "rule": "Do not pre-read later chapters or unrelated notes when a bounded prose slice is enough.",
    },
    {
        "id": "preserve-voice",
        "rule": "Preserve dialogue, speaker tags, tone, genre logic, and deliberate weirdness.",
    },
    {
        "id": "plain-helper-copy",
        "rule": "Public explanations should use direct helper-facing bullets, not meta process narration.",
    },
    {
        "id": "command-owned-doc-lane",
        "rule": "Configured document analysis commands provide evidence; failed commands are optional context.",
    },
]


def is_document_file(item: dict[str, Any]) -> bool:
    if item.get("content_kind") == "prose":
        return True
    return item.get("content_kind") == "media" and item.get("language") == "pdf"


def build_document_manifest(
    inventory: dict[str, Any],
    *,
    max_single_file_tokens: int,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for item in inventory.get("files", []):
        if not isinstance(item, dict) or not is_document_file(item):
            continue
        estimated_tokens = int(item.get("estimated_tokens", 0) or 0)
        line_count = int(item.get("line_count", 0) or 0)
        size = int(item.get("bytes", 0) or 0)
        language = str(item.get("language", ""))
        long_document = (
            estimated_tokens > max_single_file_tokens
            or line_count >= 400
            or size >= 100_000
            or language == "pdf"
        )
        files.append(
            {
                "path": item.get("path", ""),
                "content_kind": item.get("content_kind", ""),
                "language": language,
                "bytes": size,
                "line_count": line_count,
                "estimated_tokens": estimated_tokens,
                "sha256": item.get("sha256", ""),
                "summary": item.get("summary", ""),
                "long_document": long_document,
            }
        )
    files.sort(key=lambda item: (not item["long_document"], item["path"]))
    prose_files = sum(1 for item in files if item["content_kind"] == "prose")
    pdf_files = sum(1 for item in files if item["language"] == "pdf")
    return {
        "schema_version": 1,
        "summary": {
            "document_files": len(files),
            "long_document_files": sum(1 for item in files if item["long_document"]),
            "prose_files": prose_files,
            "pdf_files": pdf_files,
        },
        "rules": DOCUMENT_RULES,
        "files": files,
        "note": (
            "This manifest is for document/prose intelligence commands. It is bounded metadata, "
            "not permission for the main AI agent to freehand long-document edits."
        ),
    }
