from __future__ import annotations

import re
from pathlib import Path

from .adapters.base import AgentAdapter, AgentRequest
from .errors import SafetyError, ValidationError
from .inventory import build_inventory
from .runner import CommandRunner
from .util import atomic_write_json, sha256_file


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def validate_review_evidence(review: dict, repo: Path) -> list[dict]:
    accepted: list[dict] = []
    for finding in review.get("findings", []):
        path_value = finding.get("path")
        if not path_value:
            if finding.get("blocking"):
                raise ValidationError("Blocking finding has no file path.")
            continue
        path = (repo / path_value).resolve()
        try:
            path.relative_to(repo.resolve())
        except ValueError as exc:
            raise ValidationError(f"Reviewer cited path outside repository: {path_value}") from exc
        if not path.is_file():
            raise ValidationError(f"Reviewer cited missing file: {path_value}")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = int(finding.get("start_line", 0))
        end = int(finding.get("end_line", 0))
        if start < 1 or end < start or end > len(lines):
            raise ValidationError(
                f"Reviewer cited invalid line range {path_value}:{start}-{end}"
            )
        quote = _normalized(finding.get("quote", ""))
        evidence = _normalized("\n".join(lines[start - 1 : end]))
        if quote and quote not in evidence:
            raise ValidationError(
                f"Reviewer quote does not match {path_value}:{start}-{end}"
            )
        accepted.append(finding)
    return accepted


def inventory_hashes(repo: Path, runner: CommandRunner) -> dict[str, str]:
    return {item.path: item.sha256 for item in build_inventory(repo, runner)}


def run_isolated_review(
    *,
    adapter: AgentAdapter,
    request: AgentRequest,
    runner: CommandRunner,
) -> dict:
    before = inventory_hashes(request.cwd, runner)
    response = adapter.run(request)
    after = inventory_hashes(request.cwd, runner)
    if before != after:
        changed = sorted(set(before) | set(after))
        changed = [item for item in changed if before.get(item) != after.get(item)]
        raise SafetyError("Reviewer mutated its isolated repository: " + ", ".join(changed))
    validate_review_evidence(response.data, request.cwd)
    atomic_write_json(request.output_path.with_name("review-validated.json"), response.data)
    return response.data
