from __future__ import annotations

from collections.abc import Callable, Iterator
from copy import deepcopy
from enum import StrEnum

import pytest
from pydantic import ValidationError

from animetta.orchestration.chat_contracts import (
    ChatErrorComponent,
    ChatErrorPayload,
    ChatErrorPhase,
    ChatErrorType,
    ChatIdentity,
    ChatTransportMode,
    ChatTurnCommand,
    MediaDegradationPayload,
    TTSDegradationReason,
    assert_chat_contract_catalog,
    normalize_chat_command,
    validate_chat_contract_models,
)
from animetta.orchestration.socket_events import EVENTS

MESSAGE_ID = "11111111-1111-4111-8111-111111111111"
CONVERSATION_ID = "22222222-2222-4222-8222-222222222222"
TASK_ID = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
GENERATED_IDS = (
    "44444444-4444-4444-8444-444444444444",
    "55555555-5555-4555-8555-555555555555",
    "66666666-6666-4666-8666-666666666666",
)


def _canonical_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": "你好，Alice。",
        "message_id": MESSAGE_ID,
        "conversation_id": CONVERSATION_ID,
        "task_id": TASK_ID,
        "user_id": "local-user",
        "from_name": "User",
        "source": "text",
    }
    payload.update(updates)
    return payload


def _id_factory(values: tuple[str, ...]) -> tuple[Callable[[], str], list[str]]:
    generated: list[str] = []
    iterator: Iterator[str] = iter(values)

    def factory() -> str:
        value = next(iterator)
        generated.append(value)
        return value

    return factory, generated


def _fail_id_factory() -> str:
    raise AssertionError("canonical normalization must not generate identities")


def test_chat_identity_preserves_valid_uuid_text_and_derives_turn_alias() -> None:
    identity = ChatIdentity(
        message_id=MESSAGE_ID,
        conversation_id=CONVERSATION_ID,
        task_id=TASK_ID,
    )

    assert identity.message_id == MESSAGE_ID
    assert identity.conversation_id == CONVERSATION_ID
    assert identity.task_id == TASK_ID
    assert identity.turn_id == TASK_ID


@pytest.mark.parametrize("field", ("message_id", "conversation_id", "task_id", "turn_id"))
@pytest.mark.parametrize(
    "invalid",
    (
        "not-a-uuid",
        "11111111111141118111111111111111",
        "11111111-1111-4111-8111-111111111111-extra",
        123,
        b"11111111-1111-4111-8111-111111111111",
    ),
)
def test_chat_identity_rejects_malformed_or_non_string_ids(
    field: str,
    invalid: object,
) -> None:
    payload: dict[str, object] = {
        "message_id": MESSAGE_ID,
        "conversation_id": CONVERSATION_ID,
        "task_id": TASK_ID,
        "turn_id": TASK_ID,
    }
    payload[field] = invalid

    with pytest.raises(ValidationError, match=field):
        ChatIdentity.model_validate(payload)


def test_chat_identity_rejects_a_mismatched_turn_alias() -> None:
    with pytest.raises(ValidationError, match="turn_id must equal task_id"):
        ChatIdentity(
            message_id=MESSAGE_ID,
            conversation_id=CONVERSATION_ID,
            task_id=TASK_ID,
            turn_id=GENERATED_IDS[0],
        )


def test_canonical_normalization_preserves_payload_and_freezes_transport_mode() -> None:
    payload = _canonical_payload()
    original = deepcopy(payload)

    command = normalize_chat_command(
        "chat:text",
        payload,
        id_factory=_fail_id_factory,
    )

    assert command == ChatTurnCommand(
        **payload,
        turn_id=TASK_ID,
        transport_mode=ChatTransportMode.CANONICAL,
    )
    assert command.transport_mode is ChatTransportMode.CANONICAL
    assert command.turn_id == command.task_id == TASK_ID
    assert payload == original
    with pytest.raises(ValidationError, match="frozen"):
        command.transport_mode = ChatTransportMode.LEGACY


def test_command_accepts_strict_acceptance_marker() -> None:
    command = normalize_chat_command(
        "chat:text",
        _canonical_payload(is_acceptance=True),
    )

    assert command.is_acceptance is True
    assert command.is_inspection is False


def test_command_accepts_explicit_false_inspection_marker() -> None:
    command = normalize_chat_command(
        "chat:text",
        _canonical_payload(is_inspection=False),
    )

    assert command.is_inspection is False
    assert command.is_acceptance is False


def test_command_rejects_probe_before_workflow_normalization() -> None:
    with pytest.raises(
        ValidationError,
        match="probe must be filtered before normalization",
    ):
        normalize_chat_command(
            "chat:text",
            _canonical_payload(is_inspection=True),
        )


@pytest.mark.parametrize("missing_field", ("message_id", "conversation_id", "task_id"))
def test_canonical_normalization_rejects_missing_identity(
    missing_field: str,
) -> None:
    payload = _canonical_payload()
    payload.pop(missing_field)

    with pytest.raises(ValidationError, match=missing_field):
        normalize_chat_command(
            "chat:text",
            payload,
            id_factory=_fail_id_factory,
        )


@pytest.mark.parametrize("invalid_field", ("message_id", "conversation_id", "task_id"))
def test_canonical_normalization_rejects_invalid_identity(invalid_field: str) -> None:
    with pytest.raises(ValidationError, match=invalid_field):
        normalize_chat_command(
            "chat:text",
            _canonical_payload(**{invalid_field: "invalid"}),
            id_factory=_fail_id_factory,
        )


def test_legacy_normalization_generates_each_missing_identity_once() -> None:
    factory, generated = _id_factory(GENERATED_IDS)

    command = normalize_chat_command(
        "text_input",
        {"text": "旧客户端消息"},
        id_factory=factory,
    )

    assert command.message_id == GENERATED_IDS[0]
    assert command.conversation_id == GENERATED_IDS[1]
    assert command.task_id == GENERATED_IDS[2]
    assert command.turn_id == GENERATED_IDS[2]
    assert command.transport_mode is ChatTransportMode.LEGACY
    assert command.source == "text"
    assert generated == list(GENERATED_IDS)


def test_legacy_normalization_preserves_valid_supplied_ids() -> None:
    command = normalize_chat_command(
        "text_input",
        _canonical_payload(),
        id_factory=_fail_id_factory,
    )

    assert command.message_id == MESSAGE_ID
    assert command.conversation_id == CONVERSATION_ID
    assert command.task_id == TASK_ID
    assert command.turn_id == TASK_ID


def test_legacy_normalization_promotes_a_valid_turn_id_to_task_id() -> None:
    factory, generated = _id_factory(GENERATED_IDS[:2])

    command = normalize_chat_command(
        "text_input",
        {"text": "旧 turn_id", "turn_id": TASK_ID},
        id_factory=factory,
    )

    assert command.message_id == GENERATED_IDS[0]
    assert command.conversation_id == GENERATED_IDS[1]
    assert command.task_id == command.turn_id == TASK_ID
    assert generated == list(GENERATED_IDS[:2])


def test_legacy_normalization_replaces_invalid_ids_without_leaking_them() -> None:
    factory, generated = _id_factory(GENERATED_IDS)

    command = normalize_chat_command(
        "text_input",
        {
            "text": "损坏的旧身份",
            "message_id": "",
            "conversation_id": "too-long-" * 20,
            "task_id": "invalid",
            "turn_id": "also-invalid",
        },
        id_factory=factory,
    )

    assert (
        command.message_id,
        command.conversation_id,
        command.task_id,
        command.turn_id,
    ) == (*GENERATED_IDS, GENERATED_IDS[2])
    assert generated == list(GENERATED_IDS)


def test_normalization_rejects_conflicting_valid_task_and_turn_ids() -> None:
    with pytest.raises(ValidationError, match="turn_id must equal task_id"):
        normalize_chat_command(
            "text_input",
            _canonical_payload(turn_id=GENERATED_IDS[0]),
            id_factory=_fail_id_factory,
        )


@pytest.mark.parametrize("event_name", ("chat_text", "message", "legacy:text"))
def test_normalization_rejects_undeclared_aliases(event_name: str) -> None:
    with pytest.raises(KeyError, match="not declared"):
        normalize_chat_command(event_name, _canonical_payload())


def test_normalization_accepts_only_the_catalog_chat_text_contract() -> None:
    with pytest.raises(ValueError, match="does not normalize chat text"):
        normalize_chat_command("sentence", _canonical_payload())


@pytest.mark.parametrize("text", ("", "   ", "x" * 4001))
def test_chat_command_rejects_empty_or_over_length_text(text: str) -> None:
    with pytest.raises(ValidationError, match="text"):
        normalize_chat_command("chat:text", _canonical_payload(text=text))


def test_chat_command_rejects_payload_transport_mode_override() -> None:
    with pytest.raises(ValueError, match="transport_mode"):
        normalize_chat_command(
            "chat:text",
            _canonical_payload(transport_mode="legacy"),
        )


def test_all_chat_contract_models_enable_pydantic_strict_mode() -> None:
    for model in (
        ChatIdentity,
        ChatTurnCommand,
        ChatErrorPayload,
        MediaDegradationPayload,
    ):
        assert model.model_config["strict"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("text", b"hello"),
        ("text", 123),
        ("source", b"text"),
        ("source", 1),
        ("is_inspection", b"false"),
        ("is_inspection", 0),
        ("is_acceptance", "true"),
        ("is_acceptance", 1),
    ),
)
def test_command_rejects_non_wire_types(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        normalize_chat_command(
            "chat:text",
            _canonical_payload(**{field: value}),
        )


def test_command_string_limit_is_read_from_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    descriptor = EVENTS["chat"]["text"]["payload"]["text"]
    monkeypatch.setitem(descriptor, "max_length", 3)

    with pytest.raises(ValidationError, match="max_length"):
        normalize_chat_command("chat:text", _canonical_payload(text="four"))


def test_static_model_contract_matches_catalog() -> None:
    assert validate_chat_contract_models() == []


def test_static_enum_drift_is_a_startup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    descriptor = EVENTS["system"]["error"]["payload"]["type"]
    monkeypatch.setitem(
        descriptor,
        "enum",
        [*descriptor["enum"], "catalog_only_error"],
    )

    errors = validate_chat_contract_models()

    assert any("ChatErrorType enum" in error for error in errors)
    with pytest.raises(RuntimeError, match="ChatErrorType enum"):
        assert_chat_contract_catalog()


def test_static_default_drift_is_a_startup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = EVENTS["chat"]["text"]["payload"]["is_acceptance?"]
    monkeypatch.setitem(descriptor, "default", True)

    errors = validate_chat_contract_models()

    assert any("is_acceptance default" in error for error in errors)


def test_static_field_type_drift_is_a_startup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = EVENTS["chat"]["text"]["payload"]
    monkeypatch.setitem(
        payload,
        "text",
        {
            "type": "integer",
            "required": True,
            "strict": True,
        },
    )

    errors = validate_chat_contract_models()

    assert any("ChatTurnCommand text type" in error for error in errors)


def test_static_required_field_set_drift_is_a_startup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = EVENTS["system"]["error"]["payload"]
    monkeypatch.setitem(
        payload,
        "new_required",
        {
            "type": "string",
            "required": True,
            "strict": True,
            "min_length": 1,
            "max_length": 32,
        },
    )

    errors = validate_chat_contract_models()

    assert any("ChatErrorPayload field set" in error for error in errors)


def test_static_golden_role_cannot_be_removed_with_both_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = EVENTS["chat"]["text"]
    monkeypatch.delitem(definition, "golden_path")
    monkeypatch.delitem(definition, "identity")

    errors = validate_chat_contract_models()

    assert any("chat.text golden role" in error for error in errors)


@pytest.mark.parametrize("value", (b"legacy", 1))
def test_transport_mode_rejects_non_string_enum_inputs(value: object) -> None:
    payload = _canonical_payload()
    with pytest.raises(ValidationError, match="transport_mode"):
        ChatTurnCommand(
            **payload,
            turn_id=TASK_ID,
            transport_mode=value,
        )


def test_chat_contract_enums_are_strings_for_transport_serialization() -> None:
    for enum_type in (
        ChatTransportMode,
        ChatErrorType,
        ChatErrorComponent,
        ChatErrorPhase,
        TTSDegradationReason,
    ):
        assert issubclass(enum_type, StrEnum)


def test_typed_command_fields_remain_aligned_with_catalog_schema() -> None:
    catalog_fields = {field.removesuffix("?") for field in EVENTS["chat"]["text"]["payload"]}
    assert set(ChatTurnCommand.model_fields) == catalog_fields | {
        "turn_id",
        "transport_mode",
    }


def test_typed_error_and_degradation_fields_remain_aligned_with_catalog() -> None:
    error_fields = {field.removesuffix("?") for field in EVENTS["system"]["error"]["payload"]}
    assert set(ChatErrorPayload.model_fields) == error_fields

    control = EVENTS["chat"]["control"]
    degradation_fields = {
        "message_id",
        "conversation_id",
        "task_id",
        "turn_id",
        "text",
        *control["degradation"]["required_fields"],
    }
    assert set(MediaDegradationPayload.model_fields) == degradation_fields


def test_typed_error_payload_requires_correlated_identity_and_failure_type() -> None:
    error = ChatErrorPayload(
        message_id=MESSAGE_ID,
        conversation_id=CONVERSATION_ID,
        task_id=TASK_ID,
        type=ChatErrorType.VALIDATION,
        message="Invalid canonical identity",
        component=ChatErrorComponent.TRANSPORT,
        phase=ChatErrorPhase.VALIDATION,
        retryable=False,
        terminal=True,
    )

    assert error.turn_id == TASK_ID
    assert error.model_dump(mode="json") == {
        "message_id": MESSAGE_ID,
        "conversation_id": CONVERSATION_ID,
        "task_id": TASK_ID,
        "turn_id": TASK_ID,
        "type": "validation_error",
        "message": "Invalid canonical identity",
        "component": "transport",
        "phase": "validation",
        "retryable": False,
        "terminal": True,
    }


def test_typed_error_payload_rejects_unknown_failure_category() -> None:
    with pytest.raises(ValidationError, match="component"):
        ChatErrorPayload(
            message_id=MESSAGE_ID,
            conversation_id=CONVERSATION_ID,
            task_id=TASK_ID,
            type="validation_error",
            message="Invalid",
            component="unknown",
            phase="validation",
            retryable=False,
            terminal=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("type", b"validation_error"),
        ("type", 1),
        ("component", b"transport"),
        ("component", 1),
        ("phase", b"validation"),
        ("phase", 1),
        ("message", b"Invalid"),
        ("message", 1),
        ("retryable", b"false"),
        ("retryable", 0),
        ("terminal", "true"),
        ("terminal", 1),
    ),
)
def test_typed_error_rejects_non_wire_types(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "message_id": MESSAGE_ID,
        "conversation_id": CONVERSATION_ID,
        "task_id": TASK_ID,
        "type": "validation_error",
        "message": "Invalid",
        "component": "transport",
        "phase": "validation",
        "retryable": False,
        "terminal": True,
    }
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        ChatErrorPayload.model_validate(payload)


def test_error_message_limit_is_read_from_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    descriptor = EVENTS["system"]["error"]["payload"]["message"]
    monkeypatch.setitem(descriptor, "max_length", 3)

    with pytest.raises(ValidationError, match="max_length"):
        ChatErrorPayload(
            message_id=MESSAGE_ID,
            conversation_id=CONVERSATION_ID,
            task_id=TASK_ID,
            type="validation_error",
            message="four",
            component="transport",
            phase="validation",
            retryable=False,
            terminal=True,
        )


def test_typed_tts_degradation_payload_is_retryable_and_correlated() -> None:
    degradation = MediaDegradationPayload(
        message_id=MESSAGE_ID,
        conversation_id=CONVERSATION_ID,
        task_id=TASK_ID,
        reason=TTSDegradationReason.TIMEOUT,
        text="Audio unavailable for this turn.",
    )

    assert degradation.turn_id == TASK_ID
    assert degradation.model_dump(mode="json") == {
        "message_id": MESSAGE_ID,
        "conversation_id": CONVERSATION_ID,
        "task_id": TASK_ID,
        "turn_id": TASK_ID,
        "type": "media-degraded",
        "status": "degraded",
        "component": "tts",
        "phase": "media",
        "reason": "timeout",
        "retryable": True,
        "text": "Audio unavailable for this turn.",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("type", "fallback-audio"),
        ("status", "ready"),
        ("component", "mock_tts"),
        ("phase", "workflow"),
        ("reason", "unknown"),
        ("retryable", "yes"),
    ),
)
def test_typed_tts_degradation_rejects_untyped_states(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "message_id": MESSAGE_ID,
        "conversation_id": CONVERSATION_ID,
        "task_id": TASK_ID,
        "reason": "timeout",
    }
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        MediaDegradationPayload.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("type", b"media-degraded"),
        ("type", 1),
        ("status", b"degraded"),
        ("status", 1),
        ("component", b"tts"),
        ("component", 1),
        ("phase", b"media"),
        ("phase", 1),
        ("reason", b"timeout"),
        ("reason", 1),
        ("retryable", b"true"),
        ("retryable", 1),
        ("text", b"Unavailable"),
        ("text", 1),
    ),
)
def test_typed_tts_degradation_rejects_non_wire_types(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "message_id": MESSAGE_ID,
        "conversation_id": CONVERSATION_ID,
        "task_id": TASK_ID,
        "reason": "timeout",
    }
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        MediaDegradationPayload.model_validate(payload)
