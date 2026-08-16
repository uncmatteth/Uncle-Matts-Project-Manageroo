from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ValidationError
from .runtime_contract import required_capability_ids, runtime_capability_records


def _required_capabilities(orchestrator: Any) -> set[str]:
    explicit = getattr(orchestrator, "required_runtime_capabilities", ())
    if callable(explicit):
        explicit = explicit()
    if not isinstance(explicit, (list, tuple, set, frozenset)):
        explicit = ()
    return set(required_capability_ids(orchestrator.config, explicit))


def _record(records: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(
        (item for item in records if item.get("name") == name),
        {"name": name, "enabled": False, "ok": False},
    )


def _validate_required_discovery(
    payload: dict[str, Any], required: set[str]
) -> None:
    records = list(payload.get("records", []) or [])
    names: list[str] = []
    if "gbrain" in required:
        names.append("gbrain-search")
    if "gitnexus" in required:
        names.extend(("gitnexus-analyze", "gitnexus-query"))
    for name in names:
        item = _record(records, name)
        if not item.get("enabled"):
            raise ValidationError(
                f"The requested Manageroo operation requires {name}, but it is not configured."
            )
        if not item.get("ok"):
            detail = str(
                item.get("error") or item.get("stderr") or "command failed"
            )
            raise ValidationError(
                f"The requested Manageroo operation requires {name}, and it failed: {detail}"
            )


def install_portable_core_policy(
    orchestrator_module: Any, readiness_module: Any
) -> None:
    orchestrator_class = orchestrator_module.Orchestrator
    if getattr(orchestrator_class, "_manageroo_portable_core_policy_installed", False):
        return

    def full_enhanced_stack_available(self: Any) -> bool:
        records = runtime_capability_records(self.config)
        return bool(records) and all(bool(item.get("available")) for item in records)

    # The old switch meant "this is not the mock adapter" and consequently made
    # every surrounding integration mandatory. It now means exactly what its
    # callers need: the complete enhanced stack is actually present.
    orchestrator_class._required_stack_enabled = full_enhanced_stack_available

    requested = getattr(readiness_module, "requested_intelligence_lanes", None)
    if callable(requested):
        def requested_intelligence_lanes(brief_text: str) -> dict[str, bool]:
            lanes = dict(requested(brief_text))
            mentions = getattr(
                readiness_module, "_mentions", lambda _text, _terms: []
            )
            terms = getattr(
                readiness_module, "EXPLICIT_EXTERNAL_MEMORY_TERMS", ()
            )
            lanes["gbrain-search"] = bool(mentions(brief_text, terms))
            return lanes

        readiness_module.requested_intelligence_lanes = requested_intelligence_lanes
        # Orchestrator imported the function before package policies were installed.
        orchestrator_module.requested_intelligence_lanes = requested_intelligence_lanes

    original_values = orchestrator_class._external_values

    def external_values(self: Any, *, brief: str) -> dict[str, str]:
        values = original_values(self, brief=brief)
        if self.config.get("integrations", {}).get("gbrain_search_command"):
            source = orchestrator_module.gbrain_repo_source_item(self.source_repo)
            if source.get("ok"):
                values["gbrain_query_payload"] = orchestrator_module.gbrain_query_payload(
                    brief, source
                )
        return values

    orchestrator_class._external_values = external_values

    original_optional_command = orchestrator_class._run_optional_external_command

    def optional_command(self: Any, **kwargs: Any) -> dict[str, Any]:
        item = original_optional_command(self, **kwargs)
        if kwargs.get("name") == "gbrain-search":
            source = orchestrator_module.gbrain_repo_source_item(self.source_repo)
            if source.get("ok"):
                item = orchestrator_module.scope_gbrain_search_record(item, source)
        return item

    orchestrator_class._run_optional_external_command = optional_command

    original_external_intelligence = orchestrator_class._external_intelligence

    def external_intelligence(
        self: Any, brief: str, inventory: dict[str, Any]
    ) -> dict[str, Any]:
        required = _required_capabilities(self)
        if "gbrain" in required:
            source = orchestrator_module.gbrain_repo_source_item(self.source_repo)
            if not source.get("ok"):
                raise ValidationError(
                    "The requested GBrain lane has no healthy exact source mapping for "
                    "this repository. "
                    + str(source.get("next") or "Run manageroo gbrain-setup.")
                )
        payload = original_external_intelligence(self, brief, inventory)
        _validate_required_discovery(payload, required)
        payload.setdefault("summary", {})["required_capabilities"] = sorted(required)
        return payload

    orchestrator_class._external_intelligence = external_intelligence

    original_capture = orchestrator_class._capture_external_outcome

    def capture_external_outcome(
        self: Any,
        *,
        report_path: Path,
        result_path: Path,
        patch_path: Path,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        required = _required_capabilities(self)
        if "gbrain" not in required:
            return original_capture(
                self,
                report_path=report_path,
                result_path=result_path,
                patch_path=patch_path,
                result=result,
            )

        # The legacy implementation already has correct exact-source and failure
        # checks when its strict flag is true. Enable that behavior only for this
        # explicitly required GBrain capture, without making unrelated lanes strict.
        sentinel = object()
        previous = self.__dict__.get("_required_stack_enabled", sentinel)
        self._required_stack_enabled = lambda: True
        try:
            return original_capture(
                self,
                report_path=report_path,
                result_path=result_path,
                patch_path=patch_path,
                result=result,
            )
        finally:
            if previous is sentinel:
                self.__dict__.pop("_required_stack_enabled", None)
            else:
                self.__dict__["_required_stack_enabled"] = previous

    orchestrator_class._capture_external_outcome = capture_external_outcome
    orchestrator_class._manageroo_portable_core_policy_installed = True
