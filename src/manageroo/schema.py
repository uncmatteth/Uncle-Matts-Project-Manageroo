from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .errors import ValidationError


def _reject_nonfinite_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant is forbidden: {value}")


def extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped, parse_constant=_reject_nonfinite_constant)
    except (json.JSONDecodeError, ValueError):
        decoder = json.JSONDecoder(parse_constant=_reject_nonfinite_constant)
        for index, char in enumerate(stripped):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[index:])
                return value
            except (json.JSONDecodeError, ValueError):
                continue
    raise ValidationError("Agent output did not contain valid strict JSON.")


def _is_type(value: Any, expected: str) -> bool:
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and not (isinstance(value, float) and not math.isfinite(value))
        )
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate(value: Any, schema: dict[str, Any], location: str = "$") -> None:
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_is_type(value, item) for item in expected):
            raise ValidationError(f"{location}: expected one of {expected}")
    elif isinstance(expected, str) and not _is_type(value, expected):
        raise ValidationError(f"{location}: expected {expected}, received {type(value).__name__}")

    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{location}: {value!r} is not in enum {schema['enum']}")

    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                raise ValidationError(f"{location}: missing required property {required!r}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{location}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValidationError(f"{location}: unknown property {key!r}")

    if isinstance(value, list):
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            raise ValidationError(f"{location}: expected at least {minimum} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate(item, item_schema, f"{location}[{index}]")

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            raise ValidationError(f"{location}: string shorter than {minimum}")


def load_schema(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, parse_constant=_reject_nonfinite_constant)
