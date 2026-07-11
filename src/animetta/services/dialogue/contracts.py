"""Strict, content-safe contracts for the two-pass Anima dialogue."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_LEAKED_MARKERS = ("<|assistant|>", "<|system|>", "```json", "[SYSTEM]")


class DialogueParseError(ValueError):
    """Typed parse failure whose diagnostic never echoes authored content."""

    def __init__(self, code: str, raw: str) -> None:
        self.code = code
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
        self.safe_excerpt = f"<sha256:{digest};chars:{len(raw)}>"[:80]
        super().__init__(f"{code}: {self.safe_excerpt}")


class _StrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @field_validator("*", mode="after")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ReasonerResult(_StrictResult):
    normal_response: str = Field(min_length=1, max_length=2000)
    stance: str = Field(min_length=1, max_length=300)
    humor: str = Field(max_length=300)
    worldview: str = Field(max_length=300)


class ComposerResult(_StrictResult):
    final_response: str = Field(min_length=1, max_length=2000)
    mood: Literal["neutral", "bright", "tired", "irritated"]
    affinity_delta: int = Field(ge=-2, le=2)


def _parse[ResultT: _StrictResult](raw: str, model: type[ResultT]) -> ResultT:
    text = (raw or "").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DialogueParseError("invalid_json", text) from exc
    if not isinstance(data, dict):
        raise DialogueParseError("invalid_json", text)
    if any(
        marker.lower() in value.lower()
        for value in data.values()
        if isinstance(value, str)
        for marker in _LEAKED_MARKERS
    ):
        raise DialogueParseError("leaked_marker", text)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise DialogueParseError("schema_invalid", text) from exc


def parse_reasoner_result(raw: str) -> ReasonerResult:
    return _parse(raw, ReasonerResult)


def parse_composer_result(raw: str) -> ComposerResult:
    return _parse(raw, ComposerResult)
