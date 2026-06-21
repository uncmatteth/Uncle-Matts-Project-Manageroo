from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import atomic_write_json, read_json, sha256_json, sha256_text

CACHE_VERSION = 1


def inventory_fingerprint(inventory: list[dict[str, Any]]) -> str:
    entries = [
        {
            "path": str(item.get("path", "")),
            "sha256": str(item.get("sha256", "")),
            "bytes": int(item.get("bytes", 0)),
        }
        for item in inventory
    ]
    return sha256_json(sorted(entries, key=lambda item: item["path"]))


def _cache_payload(
    *,
    inventory: list[dict[str, Any]],
    brief: str,
    system_map: dict,
) -> dict[str, Any]:
    return {
        "cache_version": CACHE_VERSION,
        "inventory_fingerprint": inventory_fingerprint(inventory),
        "brief_sha256": sha256_text(brief),
        "system_map": system_map,
    }


def write_system_map_cache(
    path: Path,
    *,
    inventory: list[dict[str, Any]],
    brief: str,
    system_map: dict,
) -> None:
    atomic_write_json(path, _cache_payload(inventory=inventory, brief=brief, system_map=system_map))


def load_system_map_cache(
    path: Path,
    *,
    inventory: list[dict[str, Any]],
    brief: str,
) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("cache_version") != CACHE_VERSION:
        return None
    if payload.get("inventory_fingerprint") != inventory_fingerprint(inventory):
        return None
    if payload.get("brief_sha256") != sha256_text(brief):
        return None
    system_map = payload.get("system_map")
    return system_map if isinstance(system_map, dict) else None
