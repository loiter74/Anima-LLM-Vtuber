from __future__ import annotations

from copy import deepcopy

import pytest

from animetta.orchestration.socket_events import (
    EVENTS,
    event_aliases,
    materialize_event_variant,
    resolve_socket_event,
    validate_event_catalog,
)

IDENTITY_FIELDS = ("message_id", "conversation_id", "task_id")

CORRELATED_DELIVERY_EVENTS = (
    ("chat", "interrupt"),
    ("chat", "sentence"),
    ("chat", "control"),
    ("chat", "stop_audio"),
    ("chat", "audio_with_expression"),
    ("chat", "subtitle_translation"),
    ("chat", "live2d_action"),
    ("chat", "expression"),
    ("system", "error"),
)

GOLDEN_EVENTS = (
    ("chat", "text"),
    *CORRELATED_DELIVERY_EVENTS,
)


def test_every_canonical_event_uses_one_colon_delimiter() -> None:
    for module, actions in EVENTS.items():
        for action, definition in actions.items():
            name = definition["name"]
            assert name.count(":") == 1, f"{module}.{action} is not canonical: {name}"
            assert all(name.split(":")), f"{module}.{action} has an empty namespace"


@pytest.mark.parametrize(("module", "action"), GOLDEN_EVENTS)
def test_golden_events_are_explicitly_marked(module: str, action: str) -> None:
    assert EVENTS[module][action]["golden_path"] is True


@pytest.mark.parametrize(
    ("module", "action", "aliases"),
    (
        ("chat", "text", ["text_input"]),
        ("chat", "interrupt", ["interrupt_signal"]),
        ("chat", "sentence", ["sentence"]),
        ("chat", "control", ["control"]),
        ("chat", "stop_audio", ["stop_audio"]),
        ("chat", "audio_with_expression", ["audio_with_expression"]),
        ("chat", "subtitle_translation", ["subtitle.translation"]),
        ("chat", "live2d_action", ["live2d.action"]),
        ("chat", "expression", ["expression"]),
        ("system", "error", ["error"]),
    ),
)
def test_legacy_aliases_are_declared_only_on_their_canonical_event(
    module: str,
    action: str,
    aliases: list[str],
) -> None:
    assert EVENTS[module][action]["aliases"] == aliases

    owners = [
        definition["name"]
        for actions in EVENTS.values()
        for definition in actions.values()
        if any(alias in definition.get("aliases", []) for alias in aliases)
    ]
    assert owners == [EVENTS[module][action]["name"]]
    for alias in aliases:
        resolved = resolve_socket_event(alias)
        assert (resolved.module, resolved.action) == (module, action)
        assert resolved.canonical_name == EVENTS[module][action]["name"]
        assert resolved.is_legacy is True


def test_text_command_schema_requires_the_identity_triple() -> None:
    command = EVENTS["chat"]["text"]
    assert command["identity"] == "command"
    payload = command["payload"]
    assert all(payload[field]["type"] == "string" for field in IDENTITY_FIELDS)
    assert not any(f"{field}?" in payload for field in IDENTITY_FIELDS)


@pytest.mark.parametrize(("module", "action"), CORRELATED_DELIVERY_EVENTS)
def test_every_golden_delivery_schema_requires_correlated_identity(
    module: str,
    action: str,
) -> None:
    definition = EVENTS[module][action]
    assert definition["identity"] == "correlated"
    payload = definition["payload"]
    assert all(payload[field]["type"] == "string" for field in IDENTITY_FIELDS)
    assert payload["turn_id"]["type"] == "string"


def test_sentence_catalog_declares_a_schema_valid_completion_marker() -> None:
    sentence = EVENTS["chat"]["sentence"]
    assert sentence["completion"] == {
        "constants": {"text": "", "is_complete": True},
        "context_fields": [
            "seq",
            "lang",
            "message_id",
            "conversation_id",
            "task_id",
            "turn_id",
        ],
    }
    assert sentence["payload"]["is_complete?"]["type"] == "boolean"
    payload_fields = {field.removesuffix("?") for field in sentence["payload"]}
    completion_fields = {
        *sentence["completion"]["constants"],
        *sentence["completion"]["context_fields"],
    }
    assert completion_fields.issubset(payload_fields)


def test_sentence_completion_variant_materializes_only_valid_context() -> None:
    context = {
        "seq": 2,
        "lang": "zh",
        "message_id": "11111111-1111-4111-8111-111111111111",
        "conversation_id": "22222222-2222-4222-8222-222222222222",
        "task_id": "33333333-3333-4333-8333-333333333333",
        "turn_id": "33333333-3333-4333-8333-333333333333",
        "ignored": "not copied",
    }

    payload = materialize_event_variant("chat", "sentence", "completion", context)

    assert payload == {
        "text": "",
        "is_complete": True,
        "seq": 2,
        "lang": "zh",
        "message_id": "11111111-1111-4111-8111-111111111111",
        "conversation_id": "22222222-2222-4222-8222-222222222222",
        "task_id": "33333333-3333-4333-8333-333333333333",
        "turn_id": "33333333-3333-4333-8333-333333333333",
    }


def test_sentence_completion_variant_rejects_missing_context() -> None:
    with pytest.raises(ValueError, match="missing context field 'task_id'"):
        materialize_event_variant(
            "chat",
            "sentence",
            "completion",
            {
                "seq": 2,
                "lang": "zh",
                "message_id": "11111111-1111-4111-8111-111111111111",
                "conversation_id": "22222222-2222-4222-8222-222222222222",
                "turn_id": "33333333-3333-4333-8333-333333333333",
            },
        )


def test_sentence_completion_variant_rejects_mismatched_turn_alias() -> None:
    with pytest.raises(ValueError, match="turn_id must equal task_id"):
        materialize_event_variant(
            "chat",
            "sentence",
            "completion",
            {
                "seq": 2,
                "lang": "zh",
                "message_id": "11111111-1111-4111-8111-111111111111",
                "conversation_id": "22222222-2222-4222-8222-222222222222",
                "task_id": "33333333-3333-4333-8333-333333333333",
                "turn_id": "44444444-4444-4444-8444-444444444444",
            },
        )


def test_control_catalog_declares_typed_media_degradation() -> None:
    control = EVENTS["chat"]["control"]
    for field in ("type", "status", "component", "phase", "reason"):
        assert control["payload"][f"{field}?"]["type"] == "string"
    assert control["payload"]["retryable?"]["type"] == "boolean"


def test_correlated_error_catalog_declares_typed_failure_fields() -> None:
    payload = EVENTS["system"]["error"]["payload"]
    assert all(payload[field]["type"] == "string" for field in ("type", "component", "phase"))
    assert payload["retryable"]["type"] == "boolean"
    assert payload["terminal"]["type"] == "boolean"


def test_command_catalog_declares_runtime_constraints_and_defaults() -> None:
    payload = EVENTS["chat"]["text"]["payload"]
    assert payload["text"] == {
        "type": "string",
        "required": True,
        "strict": True,
        "non_whitespace": True,
        "min_length": 1,
        "max_length": 4000,
    }
    assert payload["message_id"] == {
        "type": "string",
        "required": True,
        "strict": True,
        "format": "uuid",
        "min_length": 36,
        "max_length": 36,
    }
    assert payload["source?"] == {
        "type": "string",
        "required": False,
        "strict": True,
        "enum": ["text", "livestream"],
        "default": "text",
        "min_length": 1,
        "max_length": 16,
    }
    assert payload["is_inspection?"] == {
        "type": "boolean",
        "required": False,
        "strict": True,
        "default": False,
    }
    assert payload["is_acceptance?"] == payload["is_inspection?"]


def test_every_golden_payload_field_uses_an_explicit_strict_descriptor() -> None:
    for module, action in GOLDEN_EVENTS:
        for raw_field, descriptor in EVENTS[module][action]["payload"].items():
            assert isinstance(descriptor, dict), f"{module}.{action}.{raw_field}"
            assert descriptor["type"] in {
                "array",
                "boolean",
                "integer",
                "number",
                "object",
                "string",
            }
            assert descriptor["required"] is (not raw_field.endswith("?"))
            assert descriptor["strict"] is True


def test_error_catalog_declares_the_static_wire_enums() -> None:
    payload = EVENTS["system"]["error"]["payload"]
    assert payload["type"]["enum"] == [
        "validation_error",
        "processing_error",
        "timeout",
        "interrupted",
        "internal_error",
    ]
    assert payload["component"]["enum"] == [
        "transport",
        "workflow",
        "reasoner",
        "anima_composer",
        "tts",
        "emotion",
        "live2d",
        "delivery",
    ]
    assert payload["phase"]["enum"] == [
        "validation",
        "reasoning",
        "composition",
        "workflow",
        "media",
        "delivery",
    ]


def test_degradation_catalog_declares_constants_defaults_required_and_enum() -> None:
    control = EVENTS["chat"]["control"]
    assert control["payload"]["reason?"]["enum"] == [
        "timeout",
        "rate_limit",
        "provider_error",
        "empty_audio",
        "unavailable",
    ]
    assert control["degradation"] == {
        "constants": {
            "type": "media-degraded",
            "status": "degraded",
            "component": "tts",
            "phase": "media",
        },
        "defaults": {"retryable": True},
        "required_fields": [
            "message_id",
            "conversation_id",
            "task_id",
            "turn_id",
            "type",
            "status",
            "component",
            "phase",
            "reason",
            "retryable",
        ],
        "context_fields": [
            "message_id",
            "conversation_id",
            "task_id",
            "turn_id",
            "reason",
            "text",
        ],
    }


def test_catalog_validator_accepts_the_checked_in_registry() -> None:
    assert validate_event_catalog(EVENTS) == []


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    (
        (
            lambda catalog: catalog["chat"]["text"].update(name="chat.text"),
            "canonical event name",
        ),
        (
            lambda catalog: catalog["chat"]["text"].update(name="other:text"),
            "catalog key",
        ),
        (
            lambda catalog: catalog["chat"]["control"].update(aliases=["sentence"]),
            "duplicate alias",
        ),
        (
            lambda catalog: catalog["chat"]["text"].update(aliases=["bad alias"]),
            "invalid compatibility alias",
        ),
        (
            lambda catalog: catalog["chat"]["text"].update(aliases=["text_input", "text_input"]),
            "duplicate alias",
        ),
        (
            lambda catalog: catalog["chat"]["sentence"]["completion"]["constants"].update(
                undeclared=True
            ),
            "completion constant",
        ),
        (
            lambda catalog: catalog["chat"]["sentence"]["completion"]["constants"].update(
                is_complete="true"
            ),
            "completion constant",
        ),
        (
            lambda catalog: catalog["chat"]["sentence"]["completion"]["context_fields"].remove(
                "task_id"
            ),
            "completion context",
        ),
        (
            lambda catalog: catalog["chat"]["sentence"]["completion"]["context_fields"].append(
                "task_id"
            ),
            "duplicate completion context",
        ),
        (
            lambda catalog: catalog["chat"]["sentence"]["completion"]["context_fields"].append(
                "unknown"
            ),
            "completion context field",
        ),
        (
            lambda catalog: (
                catalog["chat"]["sentence"]["completion"]["constants"].update(
                    message_id="fixed-id"
                ),
                catalog["chat"]["sentence"]["completion"]["context_fields"].remove("message_id"),
            ),
            "completion constant",
        ),
        (
            lambda catalog: catalog["chat"]["sentence"]["payload"].pop("task_id"),
            "identity field",
        ),
        (
            lambda catalog: catalog["chat"]["sentence"].update(identity="global"),
            "identity contract",
        ),
        (
            lambda catalog: catalog["chat"]["text"].pop("identity"),
            "requires identity contract",
        ),
        (
            lambda catalog: catalog["chat"]["text"].pop("golden_path"),
            "golden_path marker",
        ),
        (
            lambda catalog: catalog.update(chat=[]),
            "module 'chat' must map to an object",
        ),
        (
            lambda catalog: catalog["chat"].update({1: {}}),
            "invalid action key",
        ),
        (
            lambda catalog: catalog["chat"].update(text="invalid"),
            "event definition",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update({"task_id?": "string"}),
            "duplicate normalized payload field",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update({"bad?name": "string"}),
            "invalid payload field",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update({"bad_type?": "mystery"}),
            "invalid schema type",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update(
                text={
                    "type": "string",
                    "required": True,
                    "strict": True,
                    "unknown": 1,
                }
            ),
            "unknown descriptor key",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update(
                {
                    "user_id?": {
                        "type": "string",
                        "required": True,
                        "strict": True,
                    }
                }
            ),
            "required flag",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update(
                {
                    "is_acceptance?": {
                        "type": "boolean",
                        "required": False,
                        "strict": True,
                        "default": "false",
                    }
                }
            ),
            "invalid default",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update(
                {
                    "text": {
                        "type": "string",
                        "required": True,
                        "strict": True,
                        "min_length": 10,
                        "max_length": 1,
                    }
                }
            ),
            "invalid string length",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update(
                {
                    "source?": {
                        "type": "string",
                        "required": False,
                        "strict": True,
                        "enum": ["text", "text"],
                        "default": "text",
                    }
                }
            ),
            "enum values must be unique",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update(text="string"),
            "golden payload field",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update(
                {
                    "text": {
                        "type": "string",
                        "required": True,
                        "strict": False,
                    }
                }
            ),
            "strict=true",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"].update(text={"nested": "string"}),
            "golden payload field",
        ),
        (
            lambda catalog: catalog["chat"]["text"]["payload"]["message_id"].update(max_length=40),
            "UUID descriptor",
        ),
        (
            lambda catalog: catalog["chat"]["control"]["degradation"]["context_fields"].append(
                "reason"
            ),
            "context_fields contains duplicates",
        ),
        (
            lambda catalog: catalog["chat"]["control"]["degradation"]["required_fields"].remove(
                "message_id"
            ),
            "cover base required",
        ),
        (
            lambda catalog: catalog["chat"]["control"]["degradation"]["constants"].update(
                component=1
            ),
            "degradation constant",
        ),
        (
            lambda catalog: catalog["chat"]["control"]["degradation"].update(unknown=True),
            "degradation has unknown keys",
        ),
        (
            lambda catalog: catalog["chat"]["control"]["payload"].pop("reason?"),
            "degradation field",
        ),
    ),
)
def test_catalog_validator_rejects_contract_drift(mutate: object, expected_error: str) -> None:
    catalog = deepcopy(EVENTS)
    mutate(catalog)  # type: ignore[operator]

    errors = validate_event_catalog(catalog)

    assert any(expected_error in error for error in errors), errors


def test_catalog_backed_resolution_distinguishes_canonical_and_legacy_names() -> None:
    canonical = resolve_socket_event("chat:text")
    legacy = resolve_socket_event("text_input")

    assert canonical.module == legacy.module == "chat"
    assert canonical.action == legacy.action == "text"
    assert canonical.canonical_name == legacy.canonical_name == "chat:text"
    assert canonical.requested_name == "chat:text"
    assert legacy.requested_name == "text_input"
    assert canonical.is_legacy is False
    assert legacy.is_legacy is True
    assert event_aliases("chat", "text") == ("text_input",)


def test_catalog_backed_resolution_rejects_an_undeclared_alias() -> None:
    with pytest.raises(KeyError, match="not declared"):
        resolve_socket_event("chat_text")


def test_catalog_validator_rejects_a_non_object_root() -> None:
    errors = validate_event_catalog([])  # type: ignore[arg-type]

    assert errors == ["event catalog root must be an object"]


def test_catalog_validator_rejects_an_empty_catalog() -> None:
    assert validate_event_catalog({}) == ["event catalog has no event definitions"]
