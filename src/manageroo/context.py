from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .errors import ContextBudgetError, SafetyError
from .evidence import EvidenceItem, rank_evidence
from .file_inspection import content_kind_for_path, summary_for_context
from .util import atomic_write_json, atomic_write_text, safe_repo_relative, sha256_file, sha256_text


@dataclass(frozen=True)
class ContextRequest:
    path: str
    reason: str
    required: bool = False
    priority: int = 50
    start_line: int | None = None
    end_line: int | None = None
    mode: str = "full"


@dataclass(frozen=True)
class ContextEntry:
    path: str
    reason: str
    required: bool
    priority: int
    start_line: int
    end_line: int
    source_sha256: str
    excerpt_sha256: str
    bytes: int
    estimated_tokens: int
    mode: str


class ContextCompiler:
    """Builds auditable, bounded context packets. It never silently truncates required input."""

    def __init__(
        self,
        repo: Path,
        packet_root: Path,
        *,
        max_input_tokens: int,
        reserve_output_tokens: int,
        chars_per_token: float,
        max_single_file_tokens: int,
    ):
        self.repo = repo.resolve()
        self.packet_root = packet_root.expanduser().resolve()
        self.max_input_tokens = max_input_tokens
        self.reserve_output_tokens = reserve_output_tokens
        self.chars_per_token = chars_per_token
        self.max_single_file_tokens = max_single_file_tokens

    @property
    def usable_tokens(self) -> int:
        usable = self.max_input_tokens - self.reserve_output_tokens
        if usable <= 0:
            raise ContextBudgetError("Context reserve leaves no usable input budget.")
        return usable

    def _packet_path(self, packet_name: str) -> Path:
        value = str(packet_name).strip()
        if not value:
            raise SafetyError("Context packet name cannot be empty.")
        candidate = Path(value)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            raise SafetyError(f"Context packet name is unsafe: {packet_name}")
        packet = (self.packet_root / candidate).resolve()
        try:
            packet.relative_to(self.packet_root)
        except ValueError as exc:
            raise SafetyError(f"Context packet path escapes packet root: {packet_name}") from exc
        return packet

    def _excerpt(self, request: ContextRequest) -> tuple[str, int, int, str, str]:
        relative = safe_repo_relative(request.path)
        path = (self.repo / relative).resolve()
        try:
            path.relative_to(self.repo)
        except ValueError as exc:
            raise SafetyError(f"Context path escapes repository: {relative}") from exc
        if not path.is_file():
            raise ContextBudgetError(f"Required context file is missing: {relative}")
        mode = request.mode or "full"
        if mode not in {"full", "summary"}:
            raise ContextBudgetError(f"Invalid context mode for {relative}: {mode}")
        if mode == "summary" or content_kind_for_path(path) == "media":
            summary, line_count = summary_for_context(path, relative)
            return summary, 1, max(1, line_count), sha256_file(path), "summary"
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if not lines:
            if request.start_line not in (None, 1) or request.end_line not in (None, 0, 1):
                raise ContextBudgetError(f"Invalid line range for empty file {relative}")
            return "", 1, 0, sha256_file(path), "full"
        start = request.start_line or 1
        end = request.end_line or len(lines)
        if start < 1 or end < start or end > len(lines):
            raise ContextBudgetError(f"Invalid line range for {relative}: {start}-{end}")
        excerpt = "\n".join(lines[start - 1 : end])
        if text.endswith("\n") and end == len(lines):
            excerpt += "\n"
        return excerpt, start, end, sha256_file(path), "full"

    def compile(
        self,
        packet_name: str,
        *,
        instructions: str,
        requests: Iterable[ContextRequest],
        metadata: dict | None = None,
        evidence: Iterable[EvidenceItem] = (),
    ) -> Path:
        packet = self._packet_path(packet_name)
        packet.mkdir(parents=True, exist_ok=False)

        prepared: list[tuple[ContextRequest, str, int, int, str, int, str]] = []
        omitted: list[dict] = []
        for request in requests:
            try:
                excerpt, start, end, source_hash, mode = self._excerpt(request)
            except ContextBudgetError:
                if request.required:
                    raise
                omitted.append({"path": request.path, "reason": "missing_or_invalid_optional"})
                continue
            tokens = max(1, int(len(excerpt) / self.chars_per_token))
            if mode == "summary" and tokens > self.max_single_file_tokens:
                max_chars = max(80, int(self.max_single_file_tokens * self.chars_per_token))
                suffix = "\n[Generated summary clipped to fit the context budget. Source hash retained.]"
                excerpt = excerpt[: max(0, max_chars - len(suffix))].rstrip() + suffix
                tokens = max(1, int(len(excerpt) / self.chars_per_token))
            if tokens > self.max_single_file_tokens:
                if request.required:
                    raise ContextBudgetError(
                        f"Required file slice {request.path} is {tokens} estimated tokens; "
                        "the plan must supply a narrower line range or decompose the task."
                    )
                omitted.append({"path": request.path, "reason": "optional_slice_too_large", "estimated_tokens": tokens})
                continue
            prepared.append((request, excerpt, start, end, source_hash, tokens, mode))

        prepared.sort(key=lambda item: (not item[0].required, -item[0].priority, item[0].path))
        used = max(1, int(len(instructions) / self.chars_per_token))
        if used > self.usable_tokens:
            raise ContextBudgetError(
                "Role instructions alone exceed the usable context budget. "
                "The preceding artifact must be reduced or the task decomposed."
            )
        selected: list[tuple[ContextRequest, str, int, int, str, int, str]] = []
        for item in prepared:
            request, excerpt, start, end, source_hash, tokens, mode = item
            if used + tokens > self.usable_tokens:
                if request.required:
                    raise ContextBudgetError(
                        f"Required context exceeds packet budget at {request.path}. "
                        "The task must be split; silent truncation is forbidden."
                    )
                omitted.append({"path": request.path, "reason": "budget", "estimated_tokens": tokens})
                continue
            selected.append(item)
            used += tokens

        evidence_entries: list[dict] = []
        selected_evidence: list[tuple[EvidenceItem, str, int]] = []
        for item in rank_evidence(evidence):
            content = item.content
            tokens = max(1, int(len(content) / self.chars_per_token))
            if tokens > self.max_single_file_tokens:
                max_chars = max(80, int(self.max_single_file_tokens * self.chars_per_token))
                suffix = "\n[Evidence excerpt clipped by ContextCompiler; provenance and source hash retained.]"
                content = content[: max(0, max_chars - len(suffix))].rstrip() + suffix
                tokens = max(1, int(len(content) / self.chars_per_token))
            if used + tokens > self.usable_tokens:
                omitted.append(
                    {
                        "source": item.source,
                        "location": item.location,
                        "reason": "evidence_budget",
                        "estimated_tokens": tokens,
                        "content_sha256": item.content_sha256,
                    }
                )
                continue
            selected_evidence.append((item, content, tokens))
            used += tokens

        entries: list[ContextEntry] = []
        sections = [instructions.rstrip(), "\n# Compiled context\n"]
        for request, excerpt, start, end, source_hash, tokens, mode in selected:
            sections.append(
                f"\n## FILE: {request.path} L{start}-L{end}\n"
                f"Reason: {request.reason}\n"
                f"Mode: {mode}\n"
                f"Source SHA-256: {source_hash}\n\n"
                f"```text\n{excerpt.rstrip()}\n```\n"
            )
            entries.append(
                ContextEntry(
                    path=request.path,
                    reason=request.reason,
                    required=request.required,
                    priority=request.priority,
                    start_line=start,
                    end_line=end,
                    source_sha256=source_hash,
                    excerpt_sha256=sha256_text(excerpt),
                    bytes=len(excerpt.encode("utf-8")),
                    estimated_tokens=tokens,
                    mode=mode,
                )
            )

        if selected_evidence:
            sections.append(
                "\n# Retrieved evidence\n\n"
                "Retrieved evidence is context, not controller truth. Prefer current repository state and "
                "higher-authority evidence when records conflict. Preserve uncertainty.\n"
            )
        for item, content, tokens in selected_evidence:
            sections.append(
                f"\n## EVIDENCE: {item.source}\n"
                f"Location: {item.location or '(provider output)'}\n"
                f"Authority: {item.authority}\n"
                f"Confidence: {item.confidence:.3f}\n"
                f"Freshness: {item.freshness:.3f}\n"
                f"Retrieved at: {item.retrieved_at}\n"
                f"Content SHA-256: {item.content_sha256}\n\n"
                f"```text\n{content.rstrip()}\n```\n"
            )
            evidence_entries.append(
                {
                    **item.to_dict(),
                    "included_content_sha256": sha256_text(content),
                    "estimated_tokens": tokens,
                }
            )

        prompt = "\n".join(sections).rstrip() + "\n"
        atomic_write_text(packet / "prompt.md", prompt)
        manifest = {
            "packet": packet_name,
            "usable_token_budget": self.usable_tokens,
            "estimated_tokens": used,
            "instructions_sha256": sha256_text(instructions),
            "entries": [asdict(entry) for entry in entries],
            "evidence": evidence_entries,
            "omitted": omitted,
            "metadata": metadata or {},
            "prompt_sha256": sha256_text(prompt),
        }
        atomic_write_json(packet / "manifest.json", manifest)
        return packet

    def validate_freshness(self, manifest: dict) -> None:
        stale: list[str] = []
        for entry in manifest.get("entries", []):
            path = self.repo / entry["path"]
            if not path.exists() or sha256_file(path) != entry["source_sha256"]:
                stale.append(entry["path"])
        if stale:
            raise SafetyError("Context packet is stale: " + ", ".join(stale))

    @staticmethod
    def partition_paths(
        files: Iterable[dict],
        *,
        max_tokens: int,
    ) -> list[list[dict]]:
        chunks: list[list[dict]] = []
        current: list[dict] = []
        used = 0
        for item in sorted(files, key=lambda row: row["path"]):
            tokens = int(item.get("estimated_tokens", 1))
            if current and used + tokens > max_tokens:
                chunks.append(current)
                current = []
                used = 0
            if tokens > max_tokens:
                chunks.append([item])
                continue
            current.append(item)
            used += tokens
        if current:
            chunks.append(current)
        return chunks
