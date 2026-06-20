from __future__ import annotations

from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR
from .util import atomic_write_json, new_run_id, read_json, slugify, utc_now


class IdeaInbox:
    def __init__(self, repo: Path):
        self.root = repo / PROJECT_DIR / "ideas"
        self.root.mkdir(parents=True, exist_ok=True)

    def add(self, text: str, category: str = "unclassified") -> Path:
        idea_id = f"{new_run_id()}-{slugify(text, 32)}"
        path = self.root / f"{idea_id}.json"
        atomic_write_json(
            path,
            {
                "id": idea_id,
                "text": text,
                "category": category,
                "status": "captured",
                "created_at": utc_now(),
                "linked_run": None,
            },
        )
        return path

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        ideas = []
        for path in sorted(self.root.glob("*.json")):
            item = read_json(path)
            if status is None or item.get("status") == status:
                ideas.append(item)
        return ideas

    def attach_pending(self, run_id: str) -> list[dict]:
        attached = []
        for path in sorted(self.root.glob("*.json")):
            item = read_json(path)
            if item.get("status") != "captured":
                continue
            item["status"] = "attached"
            item["linked_run"] = run_id
            atomic_write_json(path, item)
            attached.append(item)
        return attached
