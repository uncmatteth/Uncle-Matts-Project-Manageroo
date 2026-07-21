from __future__ import annotations

import json
import sys
from typing import Any

from .errors import SafetyError


def install_entrypoint_policy(entrypoint_module: Any) -> None:
    if getattr(entrypoint_module, "_manageroo_entrypoint_policy_installed", False):
        return
    original_decisions_main = entrypoint_module._decisions_main

    def blocking_decisions(run_root):
        if entrypoint_module.decisions_fully_resolved(run_root):
            return []
        path = run_root / "artifacts" / "planning" / "blocking-decisions.json"
        if not path.is_file():
            return []
        try:
            payload = entrypoint_module.read_json(path)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SafetyError(f"Blocking decision artifact is unreadable: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SafetyError(f"Blocking decision artifact must contain a JSON object: {path}")
        decisions = payload.get("decisions", [])
        if not isinstance(decisions, list):
            raise SafetyError(f"Blocking decision artifact field 'decisions' must be an array: {path}")
        return decisions

    def decisions_main(argv: list[str]) -> int:
        try:
            return original_decisions_main(argv)
        except EOFError:
            print("Decision answering cancelled: input ended before all choices were completed.", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("Decision answering cancelled by operator.", file=sys.stderr)
            return 2
        except SafetyError as exc:
            print(f"Cannot read blocking decisions: {exc}", file=sys.stderr)
            return 2
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, AttributeError, TypeError) as exc:
            print(f"Cannot read blocking decisions: {exc}", file=sys.stderr)
            return 2

    entrypoint_module._blocking_decisions = blocking_decisions
    entrypoint_module._decisions_main = decisions_main
    entrypoint_module._manageroo_entrypoint_policy_installed = True
