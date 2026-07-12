"""Socket.IO event name constants loaded from config/socket-events.json.

Single source of truth for all Socket.IO event names across the backend.
Import event_name() for normal lookups or EVENTS for direct catalog access.

Example:
    from animetta.orchestration.socket_events import EVENTS

    # In a handler:
    await self.sio.emit(event_name("chat", "sentence"), payload, to=sid)

    # In a graph node:
    await sio.emit(event_name("chat", "transcript"), payload, to=session_id)
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger


def _load_event_names() -> dict[str, Any]:
    """Load event name configuration from config/socket-events.json."""
    # Path: orchestration/socket_events.py -> up 4 dirs -> project root
    config_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "config"
        / "socket-events.json"
    )
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load socket-events.json: {e}, using fallback")
        return {}


EVENTS: dict[str, Any] = _load_event_names()


IDENTITY_FIELDS = ("message_id", "conversation_id", "task_id")
EVENT_DEFINITION_KEYS = {
    "name",
    "aliases",
    "golden_path",
    "identity",
    "payload",
    "ack",
    "completion",
    "degradation",
}
LEGACY_SCHEMA_TYPES = {
    "array",
    "boolean",
    "integer",
    "number",
    "number|null",
    "number[]",
    "object",
    "object[]",
    "string",
    "string|null",
    "string[]",
}
DESCRIPTOR_KEYS = {
    "type",
    "required",
    "strict",
    "default",
    "min_length",
    "max_length",
    "non_whitespace",
    "format",
    "enum",
    "const",
    "items",
}
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\??$")
ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


@dataclass(frozen=True, slots=True)
class ResolvedSocketEvent:
    """Catalog result for one canonical event name or declared alias."""

    module: str
    action: str
    canonical_name: str
    requested_name: str
    is_legacy: bool


def _catalog_entries(
    catalog: Mapping[str, Any],
) -> list[tuple[str, str, Mapping[str, Any]]]:
    entries: list[tuple[str, str, Mapping[str, Any]]] = []
    for module, actions in catalog.items():
        if not isinstance(module, str) or not isinstance(actions, Mapping):
            continue
        for action, definition in actions.items():
            if isinstance(action, str) and isinstance(definition, Mapping):
                entries.append((module, action, definition))
    return entries


def _catalog_tree_entries(
    catalog: Any,
) -> tuple[list[tuple[str, str, Mapping[str, Any]]], list[str]]:
    entries: list[tuple[str, str, Mapping[str, Any]]] = []
    errors: list[str] = []
    if not isinstance(catalog, Mapping):
        return entries, ["event catalog root must be an object"]

    for module, actions in catalog.items():
        if not isinstance(module, str) or not NAME_PATTERN.fullmatch(module):
            errors.append(f"invalid module key: {module!r}")
            continue
        if not isinstance(actions, Mapping):
            errors.append(f"module {module!r} must map to an object")
            continue
        for action, definition in actions.items():
            if not isinstance(action, str) or not NAME_PATTERN.fullmatch(action):
                errors.append(f"{module} has invalid action key: {action!r}")
                continue
            if not isinstance(definition, Mapping):
                errors.append(f"{module}.{action} event definition must be an object")
                continue
            unknown_keys = set(definition) - EVENT_DEFINITION_KEYS
            if unknown_keys:
                errors.append(
                    f"{module}.{action} has unknown definition keys: "
                    f"{sorted(unknown_keys)!r}"
                )
            entries.append((module, action, definition))
    return entries, errors


def _schema_type(schema: Any) -> str | None:
    if isinstance(schema, str):
        return schema
    if isinstance(schema, Mapping):
        schema_type = schema.get("type")
        return schema_type if isinstance(schema_type, str) else None
    return None


def _descriptor_value_errors(
    schema: Any,
    value: Any,
    *,
    location: str,
) -> list[str]:
    schema_type = _schema_type(schema)
    required = schema.get("required") if isinstance(schema, Mapping) else True
    if value is None:
        return [] if required is False else [f"{location} cannot be null"]

    valid_type = False
    if schema_type == "string":
        valid_type = isinstance(value, str)
    elif schema_type == "boolean":
        valid_type = isinstance(value, bool)
    elif schema_type == "number":
        valid_type = isinstance(value, int | float) and not isinstance(value, bool)
    elif schema_type == "integer":
        valid_type = isinstance(value, int) and not isinstance(value, bool)
    elif schema_type == "object":
        valid_type = isinstance(value, Mapping)
    elif schema_type in {"array", "number[]", "string[]", "object[]"}:
        valid_type = isinstance(value, list)
    if not valid_type:
        return [f"{location} has invalid {schema_type or 'unknown'} value type"]

    errors: list[str] = []
    if isinstance(schema, Mapping):
        if isinstance(value, str):
            min_length = schema.get("min_length")
            max_length = schema.get("max_length")
            if isinstance(min_length, int) and len(value) < min_length:
                errors.append(f"{location} is shorter than min_length")
            if isinstance(max_length, int) and len(value) > max_length:
                errors.append(f"{location} is longer than max_length")
            if schema.get("format") == "uuid":
                try:
                    parsed = UUID(value)
                except (ValueError, AttributeError):
                    errors.append(f"{location} is not a valid UUID")
                else:
                    if str(parsed).casefold() != value.casefold():
                        errors.append(
                            f"{location} is not a canonical hyphenated UUID"
                        )
            if schema.get("non_whitespace") is True and not value.strip():
                errors.append(f"{location} must contain non-whitespace text")
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            errors.append(f"{location} is not in the declared enum")
        if "const" in schema and value != schema["const"]:
            errors.append(f"{location} does not match the declared const")
        if isinstance(value, list) and "items" in schema:
            for index, item in enumerate(value):
                errors.extend(
                    _descriptor_value_errors(
                        schema["items"],
                        item,
                        location=f"{location}[{index}]",
                    )
                )
    return errors


def _validate_schema_vocabulary(
    schema: Any,
    *,
    location: str,
    golden: bool = False,
    optional: bool | None = None,
) -> list[str]:
    if isinstance(schema, str):
        if schema not in LEGACY_SCHEMA_TYPES:
            return [f"{location} has invalid schema type {schema!r}"]
        if golden:
            return [f"{location} golden payload field must use an explicit descriptor"]
        return []
    if not isinstance(schema, Mapping):
        return [f"{location} schema must be a descriptor or object"]
    if "type" in schema:
        errors: list[str] = []
        unknown_keys = set(schema) - DESCRIPTOR_KEYS
        if unknown_keys:
            errors.append(
                f"{location} has unknown descriptor key(s): "
                f"{sorted(unknown_keys)!r}"
            )
        schema_type = schema.get("type")
        if schema_type not in LEGACY_SCHEMA_TYPES:
            errors.append(f"{location} has invalid schema type {schema_type!r}")
            return errors

        required = schema.get("required")
        if optional is not None:
            expected_required = not optional
            if not isinstance(required, bool) or required is not expected_required:
                errors.append(
                    f"{location} required flag must be {expected_required}"
                )
        elif "required" in schema and not isinstance(required, bool):
            errors.append(f"{location} required flag must be a boolean")

        strict = schema.get("strict")
        if "strict" in schema and not isinstance(strict, bool):
            errors.append(f"{location} strict flag must be a boolean")
        if golden and strict is not True:
            errors.append(f"{location} golden descriptor requires strict=true")

        if schema_type == "string":
            min_length = schema.get("min_length")
            max_length = schema.get("max_length")
            for key, value in (
                ("min_length", min_length),
                ("max_length", max_length),
            ):
                if value is not None and (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                ):
                    errors.append(f"{location} {key} must be a non-negative integer")
            if (
                isinstance(min_length, int)
                and not isinstance(min_length, bool)
                and isinstance(max_length, int)
                and not isinstance(max_length, bool)
                and min_length > max_length
            ):
                errors.append(f"{location} has invalid string length bounds")
            field_format = schema.get("format")
            if field_format is not None and field_format != "uuid":
                errors.append(f"{location} has invalid string format {field_format!r}")
            if field_format == "uuid" and (
                min_length != 36 or max_length != 36
            ):
                errors.append(
                    f"{location} UUID descriptor must use 36-character bounds"
                )
            non_whitespace = schema.get("non_whitespace")
            if non_whitespace is not None and not isinstance(non_whitespace, bool):
                errors.append(
                    f"{location} non_whitespace flag must be a boolean"
                )
        elif any(
            key in schema
            for key in ("min_length", "max_length", "format", "non_whitespace")
        ):
            errors.append(f"{location} has string constraints on non-string type")

        enum_values = schema.get("enum")
        if enum_values is not None:
            if not isinstance(enum_values, list) or not enum_values:
                errors.append(f"{location} enum must be a non-empty list")
            else:
                try:
                    unique_count = len(set(enum_values))
                except TypeError:
                    unique_count = -1
                if unique_count != len(enum_values):
                    errors.append(f"{location} enum values must be unique")
                for enum_value in enum_values:
                    if _descriptor_value_errors(
                        {"type": schema_type, "required": True},
                        enum_value,
                        location=f"{location} enum",
                    ):
                        errors.append(f"{location} enum has invalid value")
                        break

        if schema_type == "array":
            if "items" not in schema:
                errors.append(f"{location} array descriptor requires items")
            else:
                errors.extend(
                    _validate_schema_vocabulary(
                        schema["items"],
                        location=f"{location} items",
                    )
                )
        elif "items" in schema:
            errors.append(f"{location} items is only valid for arrays")

        if "const" in schema:
            const_errors = _descriptor_value_errors(
                {key: value for key, value in schema.items() if key != "const"},
                schema["const"],
                location=f"{location} const",
            )
            if const_errors:
                errors.append(f"{location} has invalid const")
        if "default" in schema:
            default_value = schema["default"]
            if default_value is None and required is False:
                pass
            else:
                default_errors = _descriptor_value_errors(
                    {key: value for key, value in schema.items() if key != "default"},
                    default_value,
                    location=f"{location} default",
                )
                if default_errors:
                    errors.append(f"{location} has invalid default")
        return errors

    if golden:
        return [f"{location} golden payload field must use an explicit descriptor"]

    errors: list[str] = []
    for nested_field, nested_schema in schema.items():
        if not isinstance(nested_field, str) or not FIELD_PATTERN.fullmatch(nested_field):
            errors.append(f"{location} has invalid nested field {nested_field!r}")
            continue
        errors.extend(
            _validate_schema_vocabulary(
                nested_schema,
                location=f"{location}.{nested_field.removesuffix('?')}",
            )
        )
    return errors


def _validate_payload_schema(
    payload: Any,
    *,
    owner: str,
    golden: bool,
) -> tuple[dict[str, tuple[str, Any]], list[str]]:
    normalized: dict[str, tuple[str, Any]] = {}
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return normalized, [f"{owner} payload must be an object"]

    for raw_field, schema in payload.items():
        if not isinstance(raw_field, str) or not FIELD_PATTERN.fullmatch(raw_field):
            errors.append(f"{owner} has invalid payload field {raw_field!r}")
            continue
        field = raw_field.removesuffix("?")
        if field in normalized:
            errors.append(
                f"{owner} has duplicate normalized payload field {field!r}"
            )
            continue
        normalized[field] = (raw_field, schema)
        errors.extend(
            _validate_schema_vocabulary(
                schema,
                location=f"{owner} payload field {field!r}",
                golden=golden,
                optional=raw_field.endswith("?"),
            )
        )
    return normalized, errors


def _schema_accepts_value(schema: Any, value: Any) -> bool:
    return not _descriptor_value_errors(schema, value, location="value")


def validate_event_catalog(catalog: Any) -> list[str]:
    """Return deterministic contract errors without changing the catalog.

    Validation is intentionally side-effect free so tests, build tooling, and
    future route adapters can all use the same rules.
    """

    entries, errors = _catalog_tree_entries(catalog)
    if not entries:
        return errors or ["event catalog has no event definitions"]
    wire_name_owners: dict[str, str] = {}

    for module, action, definition in entries:
        owner = f"{module}.{action}"
        canonical_name = definition.get("name")
        if (
            not isinstance(canonical_name, str)
            or canonical_name.count(":") != 1
            or not all(canonical_name.split(":"))
        ):
            errors.append(
                f"{owner} has invalid canonical event name: {canonical_name!r}"
            )
        else:
            if canonical_name != f"{module}:{action}":
                errors.append(
                    f"{owner} canonical event name must equal its catalog key: "
                    f"{canonical_name!r}"
                )
            previous_owner = wire_name_owners.setdefault(canonical_name, owner)
            if previous_owner != owner:
                errors.append(
                    f"duplicate canonical event name {canonical_name!r}: "
                    f"{previous_owner} and {owner}"
                )

        aliases = definition.get("aliases", [])
        if not isinstance(aliases, list):
            errors.append(f"{owner} aliases must be a list")
            aliases = []
        seen_aliases: set[str] = set()
        for alias in aliases:
            if (
                not isinstance(alias, str)
                or not ALIAS_PATTERN.fullmatch(alias)
                or ":" in alias
            ):
                errors.append(f"{owner} has invalid compatibility alias: {alias!r}")
                continue
            if alias in seen_aliases:
                errors.append(f"{owner} has duplicate alias {alias!r}")
                continue
            seen_aliases.add(alias)
            previous_owner = wire_name_owners.setdefault(alias, owner)
            if previous_owner != owner:
                errors.append(
                    f"duplicate alias {alias!r}: {previous_owner} and {owner}"
                )
        has_golden_marker = "golden_path" in definition
        golden_path = definition.get("golden_path", False)
        if not isinstance(golden_path, bool):
            errors.append(f"{owner} golden_path marker must be a boolean")
            golden_path = False

        payload = definition.get("payload")
        normalized_fields, payload_errors = _validate_payload_schema(
            payload,
            owner=owner,
            golden=golden_path,
        )
        errors.extend(payload_errors)
        if not isinstance(payload, Mapping):
            continue
        fields = set(normalized_fields)

        identity_contract = definition.get("identity")
        if identity_contract not in {None, "command", "correlated"}:
            errors.append(
                f"{owner} has invalid identity contract: {identity_contract!r}"
            )
        if identity_contract is not None and not has_golden_marker:
            errors.append(
                f"{owner} identity contract requires an explicit golden_path marker"
            )
        if golden_path and identity_contract not in {"command", "correlated"}:
            errors.append(f"{owner} golden event requires identity contract")
        if not golden_path and identity_contract in {"command", "correlated"}:
            errors.append(f"{owner} identity contract requires golden_path=true")
        if identity_contract == "command":
            for field in IDENTITY_FIELDS:
                field_schema = normalized_fields.get(field, ("", None))[1]
                if _schema_type(field_schema) != "string":
                    errors.append(
                        f"{owner} is missing required identity field {field!r}"
                    )

        if identity_contract == "correlated":
            for field in (*IDENTITY_FIELDS, "turn_id"):
                field_schema = normalized_fields.get(field, ("", None))[1]
                if _schema_type(field_schema) != "string":
                    errors.append(
                        f"{owner} is missing required identity field {field!r}"
                    )

        completion = definition.get("completion")
        if completion is not None:
            if not isinstance(completion, Mapping):
                errors.append(f"{owner} completion must be an object")
            else:
                unknown_keys = set(completion) - {"constants", "context_fields"}
                if unknown_keys:
                    errors.append(
                        f"{owner} completion has unknown keys: {sorted(unknown_keys)!r}"
                    )
                constants = completion.get("constants")
                context_fields = completion.get("context_fields")
                if not isinstance(constants, Mapping):
                    errors.append(f"{owner} completion constants must be an object")
                    constants = {}
                if not isinstance(context_fields, list) or not all(
                    isinstance(field, str) for field in context_fields
                ):
                    errors.append(f"{owner} completion context_fields must be a string list")
                    context_fields = []

                seen_context: set[str] = set()
                for field in context_fields:
                    if field in seen_context:
                        errors.append(
                            f"{owner} has duplicate completion context field {field!r}"
                        )
                    seen_context.add(field)
                    if field not in fields:
                        errors.append(
                            f"{owner} completion context field {field!r} is not in payload"
                        )
                for field, value in constants.items():
                    if not isinstance(field, str) or field not in fields:
                        errors.append(
                            f"{owner} completion constant {field!r} is not in payload"
                        )
                        continue
                    if field in {*IDENTITY_FIELDS, "turn_id"}:
                        errors.append(
                            f"{owner} completion constant {field!r} must come from context"
                        )
                    field_schema = normalized_fields.get(field, ("", None))[1]
                    if not _schema_accepts_value(field_schema, value):
                        errors.append(
                            f"{owner} completion constant {field!r} has invalid type"
                        )
                overlap = set(constants) & set(context_fields)
                if overlap:
                    errors.append(
                        f"{owner} completion constants/context overlap: {sorted(overlap)!r}"
                    )
                required_fields = {
                    field
                    for field, (raw_field, _schema) in normalized_fields.items()
                    if not raw_field.endswith("?")
                }
                expected_context = required_fields - set(constants)
                if set(context_fields) != expected_context:
                    errors.append(
                        f"{owner} completion context must cover required fields "
                        f"{sorted(expected_context)!r}"
                    )
                if (
                    (module, action) == ("chat", "sentence")
                    and dict(constants) != {"text": "", "is_complete": True}
                ):
                    errors.append(
                        f"{owner} completion constants must declare empty text "
                        "and is_complete=true"
                    )

        degradation = definition.get("degradation")
        if degradation is not None:
            if not isinstance(degradation, Mapping):
                errors.append(f"{owner} degradation must be an object")
            else:
                allowed_keys = {
                    "constants",
                    "defaults",
                    "required_fields",
                    "context_fields",
                }
                unknown_keys = set(degradation) - allowed_keys
                if unknown_keys:
                    errors.append(
                        f"{owner} degradation has unknown keys: "
                        f"{sorted(unknown_keys)!r}"
                    )
                constants = degradation.get("constants")
                defaults = degradation.get("defaults")
                required_fields = degradation.get("required_fields")
                context_fields = degradation.get("context_fields")
                for label, mapping in (
                    ("constants", constants),
                    ("defaults", defaults),
                ):
                    if not isinstance(mapping, Mapping):
                        errors.append(
                            f"{owner} degradation {label} must be an object"
                        )
                        continue
                    for field, value in mapping.items():
                        if not isinstance(field, str) or field not in fields:
                            errors.append(
                                f"{owner} degradation field {field!r} is not in payload"
                            )
                            continue
                        field_schema = normalized_fields[field][1]
                        if not _schema_accepts_value(field_schema, value):
                            errors.append(
                                f"{owner} degradation {label[:-1]} "
                                f"{field!r} has invalid value"
                            )
                if isinstance(constants, Mapping) and isinstance(defaults, Mapping):
                    overlap = set(constants) & set(defaults)
                    if overlap:
                        errors.append(
                            f"{owner} degradation constants/defaults overlap: "
                            f"{sorted(overlap)!r}"
                        )

                for label, field_list in (
                    ("required_fields", required_fields),
                    ("context_fields", context_fields),
                ):
                    if not isinstance(field_list, list) or not all(
                        isinstance(field, str) for field in field_list
                    ):
                        errors.append(
                            f"{owner} degradation {label} must be a string list"
                        )
                        continue
                    if len(field_list) != len(set(field_list)):
                        errors.append(
                            f"{owner} degradation {label} contains duplicates"
                        )
                    for field in field_list:
                        if field not in fields:
                            errors.append(
                                f"{owner} degradation field {field!r} is not in payload"
                            )

                if all(
                    isinstance(value, expected_type)
                    for value, expected_type in (
                        (constants, Mapping),
                        (defaults, Mapping),
                        (required_fields, list),
                        (context_fields, list),
                    )
                ):
                    constructible = (
                        set(constants) | set(defaults) | set(context_fields)
                    )
                    if not set(required_fields).issubset(constructible):
                        errors.append(
                            f"{owner} degradation required fields are not constructible"
                        )
                    base_required = {
                        field
                        for field, (raw_field, _schema) in normalized_fields.items()
                        if not raw_field.endswith("?")
                    }
                    if not base_required.issubset(set(required_fields)):
                        errors.append(
                            f"{owner} degradation required_fields must cover "
                            "base required payload fields"
                        )
                    if not (set(constants) | set(defaults)).issubset(
                        set(required_fields)
                    ):
                        errors.append(
                            f"{owner} degradation constants/defaults must be required"
                        )

    return errors


def event_payload_descriptor(
    module: str,
    action: str,
    field: str,
) -> Mapping[str, Any]:
    """Return one normalized rich payload descriptor from the catalog."""

    try:
        payload = EVENTS[module][action]["payload"]
    except KeyError as exc:
        raise KeyError(
            f"Socket.IO event not configured: {module}.{action}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise KeyError(f"Socket.IO event has invalid payload: {module}.{action}")
    matches = [
        schema
        for raw_field, schema in payload.items()
        if isinstance(raw_field, str) and raw_field.removesuffix("?") == field
    ]
    if len(matches) != 1 or not isinstance(matches[0], Mapping):
        raise KeyError(
            f"Socket.IO event field has no rich descriptor: "
            f"{module}.{action}.{field}"
        )
    return matches[0]


def validate_event_field_value(
    module: str,
    action: str,
    field: str,
    value: Any,
) -> Any:
    """Validate a wire value against its catalog descriptor without coercion."""

    descriptor = event_payload_descriptor(module, action, field)
    errors = _descriptor_value_errors(
        descriptor,
        value,
        location=f"{module}.{action}.{field}",
    )
    if errors:
        raise ValueError("; ".join(errors))
    return value


def event_field_default(module: str, action: str, field: str) -> Any:
    """Return a validated catalog default for one optional field."""

    descriptor = event_payload_descriptor(module, action, field)
    if "default" not in descriptor:
        raise KeyError(f"Socket.IO event field has no default: {module}.{action}.{field}")
    value = descriptor["default"]
    return validate_event_field_value(module, action, field, value)


def event_variant_value(
    module: str,
    action: str,
    variant: str,
    section: str,
    field: str,
) -> Any:
    """Return and validate a constant/default declared by an event variant."""

    try:
        values = EVENTS[module][action][variant][section]
        value = values[field]
    except (KeyError, TypeError) as exc:
        raise KeyError(
            f"Socket.IO event variant value not configured: "
            f"{module}.{action}.{variant}.{section}.{field}"
        ) from exc
    return validate_event_field_value(module, action, field, value)


def materialize_event_variant(
    module: str,
    action: str,
    variant: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one catalog-declared event variant from validated context."""

    try:
        definition = EVENTS[module][action]
        payload_schema = definition["payload"]
        variant_schema = definition[variant]
    except KeyError as exc:
        raise KeyError(
            f"Socket.IO event variant not configured: {module}.{action}.{variant}"
        ) from exc
    if not isinstance(payload_schema, Mapping) or not isinstance(variant_schema, Mapping):
        raise ValueError(f"Invalid event variant schema: {module}.{action}.{variant}")

    constants = variant_schema.get("constants")
    defaults = variant_schema.get("defaults", {})
    context_fields = variant_schema.get("context_fields")
    required_fields = variant_schema.get("required_fields")
    if (
        not isinstance(constants, Mapping)
        or not isinstance(defaults, Mapping)
        or not isinstance(context_fields, list)
    ):
        raise ValueError(f"Invalid event variant schema: {module}.{action}.{variant}")

    result = {**constants, **defaults}
    required_context = (
        set(context_fields)
        if required_fields is None
        else set(required_fields) & set(context_fields)
    )
    for field in context_fields:
        if field not in context:
            if field in required_context:
                raise ValueError(f"missing context field {field!r}")
            continue
        result[field] = context[field]

    if isinstance(required_fields, list):
        missing = set(required_fields) - set(result)
        if missing:
            raise ValueError(f"missing required variant fields: {sorted(missing)!r}")

    for field, value in result.items():
        raw_field = field if field in payload_schema else f"{field}?"
        schema = payload_schema.get(raw_field)
        if not _schema_accepts_value(schema, value):
            raise ValueError(f"invalid variant field {field!r}")
    if (
        "task_id" in result
        and "turn_id" in result
        and result["turn_id"] != result["task_id"]
    ):
        raise ValueError("turn_id must equal task_id")
    return result


def event_aliases(module: str, action: str) -> tuple[str, ...]:
    """Return declared aliases without exposing them as ordinary constants."""

    try:
        aliases = EVENTS[module][action].get("aliases", [])
    except KeyError as exc:
        raise KeyError(
            f"Socket.IO event not configured: {module}.{action}"
        ) from exc
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) and alias for alias in aliases
    ):
        raise KeyError(f"Socket.IO event has invalid aliases: {module}.{action}")
    return tuple(aliases)


def resolve_socket_event(requested_name: str) -> ResolvedSocketEvent:
    """Resolve only a canonical event name or an explicitly declared alias."""

    for module, action, definition in _catalog_entries(EVENTS):
        canonical_name = definition.get("name")
        if not isinstance(canonical_name, str):
            continue
        if requested_name == canonical_name:
            return ResolvedSocketEvent(
                module=module,
                action=action,
                canonical_name=canonical_name,
                requested_name=requested_name,
                is_legacy=False,
            )
        aliases = definition.get("aliases", [])
        if isinstance(aliases, list) and requested_name in aliases:
            return ResolvedSocketEvent(
                module=module,
                action=action,
                canonical_name=canonical_name,
                requested_name=requested_name,
                is_legacy=True,
            )
    raise KeyError(f"Socket.IO event is not declared: {requested_name!r}")


def event_name(module: str, action: str) -> str:
    """Return a configured Socket.IO event name.

    Raises:
        KeyError: If the event is not declared in config/socket-events.json.
    """
    try:
        name = EVENTS[module][action]["name"]
    except KeyError as exc:
        raise KeyError(
            f"Socket.IO event not configured: {module}.{action}"
        ) from exc

    if not isinstance(name, str) or not name:
        raise KeyError(f"Socket.IO event has no name: {module}.{action}")
    return name
