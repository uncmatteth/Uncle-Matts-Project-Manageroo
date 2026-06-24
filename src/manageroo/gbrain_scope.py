from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def gbrain_source_scope(source_item: dict[str, Any]) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    paths: set[str] = set()
    for source in source_item.get("matched_sources", []) or []:
        if not isinstance(source, dict):
            continue
        for key in ("source_id", "sourceId", "id"):
            value = source.get(key)
            if value:
                ids.add(str(value))
        path = source.get("path")
        if path:
            paths.add(str(Path(str(path)).expanduser().resolve()))
    return ids, paths


def gbrain_query_payload(query: str, source_item: dict[str, Any], *, limit: int = 20) -> str:
    payload: dict[str, Any] = {"query": str(query), "limit": limit}
    source_id = ""
    for source in source_item.get("matched_sources", []) or []:
        if not isinstance(source, dict):
            continue
        for key in ("source_id", "sourceId", "id"):
            value = source.get(key)
            if value:
                source_id = str(value)
                break
        if source_id:
            break
    if source_id:
        payload["source_id"] = source_id
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def gbrain_result_source_values(item: Any) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    paths: set[str] = set()
    if not isinstance(item, dict):
        return ids, paths
    for key in ("source_id", "sourceId"):
        value = item.get(key)
        if isinstance(value, str) and value:
            ids.add(value)
    source = item.get("source")
    if isinstance(source, dict):
        for nested_key in ("source_id", "sourceId", "id"):
            nested = source.get(nested_key)
            if nested:
                ids.add(str(nested))
        nested_path = source.get("path")
        if nested_path:
            paths.add(str(Path(str(nested_path)).expanduser().resolve()))
    for key in ("source_path", "sourcePath", "path", "file_path", "filePath"):
        value = item.get(key)
        if isinstance(value, str) and value:
            paths.add(str(Path(value).expanduser().resolve()))
    return ids, paths


def gbrain_item_matches_source(item: Any, source_ids: set[str], source_paths: set[str]) -> bool:
    item_ids, item_paths = gbrain_result_source_values(item)
    if source_ids and item_ids and source_ids.intersection(item_ids):
        return True
    for item_path in item_paths:
        for source_path in source_paths:
            try:
                Path(item_path).relative_to(source_path)
            except ValueError:
                continue
            return True
    return False


def gbrain_payload_items(payload: Any) -> tuple[list[Any], Callable[[list[Any]], Any]]:
    if isinstance(payload, list):
        return payload, lambda items: items
    if isinstance(payload, dict):
        for key in ("results", "items", "hits", "matches"):
            value = payload.get(key)
            if isinstance(value, list):
                return value, lambda items, key=key: {key: items}
        return [payload], lambda items: items[0] if items else {}
    return [], lambda items: items


def scope_gbrain_search_record(
    record: dict[str, Any],
    source_item: dict[str, Any],
    *,
    max_chars: int = 180_000,
    allow_empty: bool = False,
) -> dict[str, Any]:
    record["stderr"] = ""
    if not record.get("ok"):
        record["stdout"] = ""
        return record
    source_ids, source_paths = gbrain_source_scope(source_item)
    if not source_ids and not source_paths:
        record["ok"] = False
        record["error_type"] = "ValidationError"
        record["error"] = "GBrain repo source proof did not include a scoped source id or path."
        record["stdout"] = ""
        return record
    stdout = str(record.get("stdout", "") or "").strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        record["ok"] = False
        record["error_type"] = "ValidationError"
        record["error"] = "GBrain search output must be JSON so Manageroo can enforce repo-source scope."
        record["stdout"] = ""
        return record
    items, rebuild = gbrain_payload_items(payload)
    filtered = [
        item
        for item in items
        if gbrain_item_matches_source(item, source_ids, source_paths)
    ]
    if not filtered and not (allow_empty and not items):
        record["ok"] = False
        record["error_type"] = "ValidationError"
        record["error"] = "GBrain search returned no results for the exact mapped repo source."
        record["stdout"] = ""
        record["gbrain_source_scope"] = {
            "source_ids": sorted(source_ids),
            "source_paths": sorted(source_paths),
            "kept": 0,
            "dropped": len(items),
        }
        return record
    filtered_stdout = json.dumps(rebuild(filtered), indent=2, sort_keys=True, ensure_ascii=False)
    if len(filtered_stdout) > max_chars:
        record["ok"] = False
        record["error_type"] = "ValidationError"
        record["error"] = "Filtered GBrain search output exceeded the deterministic prompt budget."
        record["stdout"] = ""
        return record
    record["stdout"] = filtered_stdout
    record["gbrain_source_scope"] = {
        "source_ids": sorted(source_ids),
        "source_paths": sorted(source_paths),
        "kept": len(filtered),
        "dropped": len(items) - len(filtered),
    }
    return record
