"""Typed, transport-neutral contracts for the golden chat path.

This module normalizes catalog-declared text ingress into immutable commands.
It does not register routes, mutate sessions, emit events, or invoke workflow
services; transport adapters can therefore reuse it without hidden effects.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

from animetta.orchestration.socket_events import (
    EVENTS,
    IDENTITY_FIELDS,
    event_field_default,
    event_payload_descriptor,
    event_variant_value,
    resolve_socket_event,
    validate_event_catalog,
    validate_event_field_value,
)

IdentityValue = str
ChatText = str
ShortText = str
ErrorMessage = str
NoticeText = str
IdentityFactory = Callable[[], str | UUID]

# Product-boundary invariant. These roles cannot be inferred solely from the
# mutable catalog because deleting both markers would otherwise make a golden
# event silently disappear from validation.
_GOLDEN_EVENT_ROLES: dict[tuple[str, str], str] = {
    ("chat", "text"): "command",
    ("chat", "developer_text"): "command",
    ("chat", "interrupt"): "correlated",
    ("chat", "sentence"): "correlated",
    ("chat", "control"): "correlated",
    ("chat", "stop_audio"): "correlated",
    ("chat", "audio_with_expression"): "correlated",
    ("chat", "audio_stream_start"): "correlated",
    ("chat", "audio_stream_chunk"): "correlated",
    ("chat", "audio_stream_end"): "correlated",
    ("chat", "subtitle_translation"): "correlated",
    ("chat", "live2d_action"): "correlated",
    ("chat", "expression"): "correlated",
    ("system", "error"): "correlated",
}


def _validated_uuid_text(value: Any, *, field: str = "message_id") -> str:
    descriptor_field = "task_id" if field == "turn_id" else field
    return validate_event_field_value(
        "chat",
        "text",
        descriptor_field,
        value,
    )


def _valid_uuid_text_or_none(value: Any) -> str | None:
    try:
        return _validated_uuid_text(value)
    except ValueError:
        return None


class _FrozenContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


class ChatTransportMode(StrEnum):
    """Wire generation selected for one immutable normalized turn."""

    CANONICAL = "canonical"
    LEGACY = "legacy"


class ChatIdentity(_FrozenContract):
    """Stable identity shared by command, delivery, trace, and migration alias."""

    message_id: IdentityValue
    conversation_id: IdentityValue
    task_id: IdentityValue
    turn_id: IdentityValue

    @model_validator(mode="before")
    @classmethod
    def _derive_turn_alias(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        if "turn_id" not in data and "task_id" in data:
            data["turn_id"] = data["task_id"]
        return data

    @field_validator("message_id", "conversation_id", "task_id", "turn_id", mode="before")
    @classmethod
    def _validate_uuid(cls, value: Any, info: ValidationInfo) -> str:
        return _validated_uuid_text(value, field=info.field_name)

    @model_validator(mode="after")
    def _require_turn_alias(self) -> Self:
        if self.turn_id != self.task_id:
            raise ValueError("turn_id must equal task_id")
        return self


class ChatTurnCommand(ChatIdentity):
    """Canonical workflow input produced by the transport compatibility layer."""

    text: ChatText
    transport_mode: ChatTransportMode
    user_id: ShortText | None = event_field_default("chat", "text", "user_id")
    from_name: ShortText | None = event_field_default("chat", "text", "from_name")
    source: str = event_field_default("chat", "text", "source")
    is_inspection: bool = event_field_default("chat", "text", "is_inspection")
    is_acceptance: bool = event_field_default("chat", "text", "is_acceptance")

    @field_validator(
        "text",
        "user_id",
        "from_name",
        "source",
        "is_inspection",
        "is_acceptance",
        mode="before",
    )
    @classmethod
    def _validate_command_field(cls, value: Any, info: ValidationInfo) -> Any:
        return validate_event_field_value("chat", "text", info.field_name, value)

    @field_validator("transport_mode", mode="before")
    @classmethod
    def _validate_transport_mode(cls, value: Any) -> ChatTransportMode:
        if isinstance(value, ChatTransportMode):
            return value
        if not isinstance(value, str):
            raise ValueError("transport_mode must be a string enum")
        try:
            return ChatTransportMode(value)
        except ValueError as exc:
            raise ValueError("invalid transport_mode") from exc

    @field_validator("is_inspection")
    @classmethod
    def _reject_unfiltered_probe(cls, value: bool) -> bool:
        if value:
            raise ValueError("probe must be filtered before normalization")
        return value


class ChatErrorType(StrEnum):
    VALIDATION = "validation_error"
    PROCESSING = "processing_error"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"
    INTERNAL = "internal_error"


class ChatErrorComponent(StrEnum):
    TRANSPORT = "transport"
    WORKFLOW = "workflow"
    REASONER = "reasoner"
    COMPOSER = "anima_composer"
    TTS = "tts"
    EMOTION = "emotion"
    LIVE2D = "live2d"
    DELIVERY = "delivery"


class ChatErrorPhase(StrEnum):
    VALIDATION = "validation"
    REASONING = "reasoning"
    COMPOSITION = "composition"
    WORKFLOW = "workflow"
    MEDIA = "media"
    DELIVERY = "delivery"


class ChatErrorPayload(ChatIdentity):
    """Correlated, content-bounded error sent through system:error."""

    type: ChatErrorType
    message: ErrorMessage
    component: ChatErrorComponent
    phase: ChatErrorPhase
    retryable: bool
    terminal: bool

    @field_validator("type", "component", "phase", mode="before")
    @classmethod
    def _validate_error_enum(cls, value: Any, info: ValidationInfo) -> StrEnum:
        enum_types = {
            "type": ChatErrorType,
            "component": ChatErrorComponent,
            "phase": ChatErrorPhase,
        }
        enum_type = enum_types[info.field_name]
        if isinstance(value, enum_type):
            wire_value = value.value
        elif isinstance(value, str):
            wire_value = value
        else:
            raise ValueError(f"{info.field_name} must be a string enum")
        validate_event_field_value(
            "system",
            "error",
            info.field_name,
            wire_value,
        )
        return enum_type(wire_value)

    @field_validator("message", "retryable", "terminal", mode="before")
    @classmethod
    def _validate_error_field(cls, value: Any, info: ValidationInfo) -> Any:
        return validate_event_field_value(
            "system",
            "error",
            info.field_name,
            value,
        )


class TTSDegradationReason(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    PROVIDER_ERROR = "provider_error"
    EMPTY_AUDIO = "empty_audio"
    UNAVAILABLE = "unavailable"


class MediaDegradationPayload(ChatIdentity):
    """Typed control payload for one real-provider media degradation."""

    type: str = event_variant_value("chat", "control", "degradation", "constants", "type")
    status: str = event_variant_value("chat", "control", "degradation", "constants", "status")
    component: str = event_variant_value("chat", "control", "degradation", "constants", "component")
    phase: str = event_variant_value("chat", "control", "degradation", "constants", "phase")
    reason: TTSDegradationReason
    retryable: bool = event_variant_value("chat", "control", "degradation", "defaults", "retryable")
    text: NoticeText | None = event_field_default("chat", "control", "text")

    @field_validator("type", "status", "component", "phase", mode="before")
    @classmethod
    def _validate_degradation_constant(
        cls,
        value: Any,
        info: ValidationInfo,
    ) -> str:
        validate_event_field_value("chat", "control", info.field_name, value)
        expected = event_variant_value(
            "chat",
            "control",
            "degradation",
            "constants",
            info.field_name,
        )
        if value != expected:
            raise ValueError(f"{info.field_name} does not match degradation constant")
        return value

    @field_validator("reason", mode="before")
    @classmethod
    def _validate_degradation_reason(cls, value: Any) -> TTSDegradationReason:
        if isinstance(value, TTSDegradationReason):
            wire_value = value.value
        elif isinstance(value, str):
            wire_value = value
        else:
            raise ValueError("reason must be a string enum")
        validate_event_field_value("chat", "control", "reason", wire_value)
        return TTSDegradationReason(wire_value)

    @field_validator("retryable", "text", mode="before")
    @classmethod
    def _validate_degradation_field(
        cls,
        value: Any,
        info: ValidationInfo,
    ) -> Any:
        validate_event_field_value("chat", "control", info.field_name, value)
        if info.field_name == "retryable":
            expected = event_variant_value(
                "chat",
                "control",
                "degradation",
                "defaults",
                "retryable",
            )
            if value != expected:
                raise ValueError("retryable does not match degradation default")
        return value


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


def validate_chat_contract_models() -> list[str]:
    """Return catalog/model drift errors checked during module startup."""

    errors = validate_event_catalog(EVENTS)
    enum_contracts = (
        (
            "ChatErrorType",
            ChatErrorType,
            event_payload_descriptor("system", "error", "type"),
        ),
        (
            "ChatErrorComponent",
            ChatErrorComponent,
            event_payload_descriptor("system", "error", "component"),
        ),
        (
            "ChatErrorPhase",
            ChatErrorPhase,
            event_payload_descriptor("system", "error", "phase"),
        ),
        (
            "TTSDegradationReason",
            TTSDegradationReason,
            event_payload_descriptor("chat", "control", "reason"),
        ),
    )
    for label, enum_type, descriptor in enum_contracts:
        if descriptor.get("enum") != _enum_values(enum_type):
            errors.append(f"{label} enum does not match socket-events.json")

    model_field_types = (
        (
            "ChatTurnCommand",
            "chat",
            "text",
            {
                "text": "string",
                "message_id": "string",
                "conversation_id": "string",
                "task_id": "string",
                "user_id": "string",
                "from_name": "string",
                "source": "string",
                "is_inspection": "boolean",
                "is_acceptance": "boolean",
            },
        ),
        (
            "ChatErrorPayload",
            "system",
            "error",
            {
                "type": "string",
                "message": "string",
                "message_id": "string",
                "conversation_id": "string",
                "task_id": "string",
                "turn_id": "string",
                "component": "string",
                "phase": "string",
                "retryable": "boolean",
                "terminal": "boolean",
            },
        ),
        (
            "MediaDegradationPayload",
            "chat",
            "control",
            {
                "message_id": "string",
                "conversation_id": "string",
                "task_id": "string",
                "turn_id": "string",
                "type": "string",
                "status": "string",
                "component": "string",
                "phase": "string",
                "reason": "string",
                "retryable": "boolean",
                "text": "string",
            },
        ),
    )
    for model_name, module, action, fields in model_field_types:
        for field, expected_type in fields.items():
            descriptor = event_payload_descriptor(module, action, field)
            if descriptor.get("type") != expected_type:
                errors.append(f"{model_name} {field} type does not match catalog")

    catalog_command_fields = {
        field.removesuffix("?") for field in EVENTS["chat"]["text"]["payload"]
    }
    field_set_contracts = (
        (
            "ChatTurnCommand",
            set(ChatTurnCommand.model_fields),
            catalog_command_fields | {"turn_id", "transport_mode"},
        ),
        (
            "ChatErrorPayload",
            set(ChatErrorPayload.model_fields),
            {field.removesuffix("?") for field in EVENTS["system"]["error"]["payload"]},
        ),
        (
            "MediaDegradationPayload",
            set(MediaDegradationPayload.model_fields),
            set(EVENTS["chat"]["control"]["degradation"]["constants"])
            | set(EVENTS["chat"]["control"]["degradation"]["defaults"])
            | set(EVENTS["chat"]["control"]["degradation"]["context_fields"]),
        ),
    )
    for model_name, model_fields, catalog_fields in field_set_contracts:
        if model_fields != catalog_fields:
            missing = sorted(catalog_fields - model_fields)
            extra = sorted(model_fields - catalog_fields)
            errors.append(
                f"{model_name} field set does not match catalog (missing={missing}, extra={extra})"
            )

    for (module, action), expected_identity in _GOLDEN_EVENT_ROLES.items():
        try:
            definition = EVENTS[module][action]
        except (KeyError, TypeError):
            errors.append(f"{module}.{action} golden role is missing")
            continue
        if (
            not isinstance(definition, Mapping)
            or definition.get("golden_path") is not True
            or definition.get("identity") != expected_identity
        ):
            errors.append(
                f"{module}.{action} golden role must be "
                f"golden_path=true identity={expected_identity}"
            )

    for field in (
        "user_id",
        "from_name",
        "source",
        "is_inspection",
        "is_acceptance",
    ):
        model_default = ChatTurnCommand.model_fields[field].default
        catalog_default = event_payload_descriptor(
            "chat",
            "text",
            field,
        ).get("default")
        if model_default != catalog_default:
            errors.append(f"ChatTurnCommand {field} default does not match catalog")

    for field in ("type", "status", "component", "phase"):
        model_default = MediaDegradationPayload.model_fields[field].default
        catalog_default = event_variant_value(
            "chat",
            "control",
            "degradation",
            "constants",
            field,
        )
        if model_default != catalog_default:
            errors.append(f"MediaDegradationPayload {field} default does not match catalog")
    retryable_default = MediaDegradationPayload.model_fields["retryable"].default
    catalog_retryable = event_variant_value(
        "chat",
        "control",
        "degradation",
        "defaults",
        "retryable",
    )
    if retryable_default != catalog_retryable:
        errors.append("MediaDegradationPayload retryable default does not match catalog")

    canonical_identity = event_payload_descriptor(
        "chat",
        "text",
        "message_id",
    )
    for module, actions in EVENTS.items():
        if not isinstance(actions, Mapping):
            continue
        for action, definition in actions.items():
            if not isinstance(definition, Mapping) or not definition.get("golden_path"):
                continue
            identity_fields = (
                (*IDENTITY_FIELDS, "turn_id")
                if definition.get("identity") == "correlated"
                else IDENTITY_FIELDS
            )
            for field in identity_fields:
                descriptor_field = "task_id" if field == "turn_id" else field
                descriptor = event_payload_descriptor(module, action, field)
                reference = (
                    event_payload_descriptor("chat", "text", descriptor_field)
                    if descriptor_field != "message_id"
                    else canonical_identity
                )
                if descriptor != reference:
                    errors.append(
                        f"{module}.{action}.{field} identity descriptor "
                        "does not match command identity constraints"
                    )
    return errors


def assert_chat_contract_catalog() -> None:
    """Fail startup when static model APIs drift from the event catalog."""

    errors = validate_chat_contract_models()
    if errors:
        raise RuntimeError("Invalid chat contract catalog: " + "; ".join(errors))


assert_chat_contract_catalog()


def _new_identity(id_factory: IdentityFactory) -> str:
    generated = id_factory()
    value = str(generated) if isinstance(generated, UUID) else generated
    try:
        return _validated_uuid_text(value)
    except ValueError as exc:
        raise ValueError("id_factory must return a valid UUID") from exc


def _normalize_legacy_identities(
    payload: dict[str, Any],
    *,
    id_factory: IdentityFactory,
) -> None:
    for field in ("message_id", "conversation_id"):
        valid_value = _valid_uuid_text_or_none(payload.get(field))
        payload[field] = valid_value or _new_identity(id_factory)

    task_id = _valid_uuid_text_or_none(payload.get("task_id"))
    turn_id = _valid_uuid_text_or_none(payload.get("turn_id"))
    if task_id is not None and turn_id is not None and task_id != turn_id:
        return

    normalized_task_id = task_id or turn_id or _new_identity(id_factory)
    payload["task_id"] = normalized_task_id
    payload["turn_id"] = normalized_task_id


def normalize_chat_command(
    event: str,
    payload: Mapping[str, Any],
    *,
    id_factory: IdentityFactory = uuid4,
) -> ChatTurnCommand:
    """Normalize one catalog-declared text event into an immutable command.

    Canonical chat:text requires client-provided valid identities. The declared
    text_input adapter preserves valid legacy identities, promotes a valid
    turn_id when needed, and replaces only missing or invalid IDs.
    """

    resolution = resolve_socket_event(event)
    if resolution.module != "chat" or resolution.action not in {"text", "developer_text"}:
        raise ValueError(f"Socket.IO event {event!r} does not normalize chat text")
    if not isinstance(payload, Mapping):
        raise TypeError("chat payload must be a mapping")

    data = dict(payload)
    if "transport_mode" in data:
        raise ValueError("transport_mode is derived from the event catalog")

    if resolution.is_legacy:
        _normalize_legacy_identities(data, id_factory=id_factory)

    data["transport_mode"] = (
        ChatTransportMode.LEGACY if resolution.is_legacy else ChatTransportMode.CANONICAL
    )
    return ChatTurnCommand.model_validate(data)
