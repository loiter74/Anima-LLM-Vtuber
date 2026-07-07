"""JSON parsing and validation for Humor Agent model output."""

from __future__ import annotations

import json
import re
from typing import Any

from .models import HumorFallbackReason, HumorRewriteRequest, HumorRewriteResult

_REQUIRED_FIELDS = (
    "scene",
    "emotion",
    "humor_anchor",
    "worldview_mapping",
    "style",
    "candidate_response",
    "risk",
)

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class HumorParseError(ValueError):
    """Raised when model output cannot be parsed into a HumorRewriteResult."""

    def __init__(self, reason: HumorFallbackReason, detail: str = "") -> None:
        super().__init__(detail or str(reason))
        self.reason = reason


def _extract_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise HumorParseError(HumorFallbackReason.INVALID_JSON, "empty response")

    fenced = _FENCED_JSON_RE.search(text)
    if fenced:
        return fenced.group(1).strip()

    start = text.find("{")
    if start == -1:
        raise HumorParseError(HumorFallbackReason.INVALID_JSON, "no object start")

    decoder = json.JSONDecoder()
    try:
        _, end = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise HumorParseError(HumorFallbackReason.INVALID_JSON, str(exc)) from exc
    return text[start:start + end]


def parse_humor_result(raw: str, request: HumorRewriteRequest) -> HumorRewriteResult:
    """Parse a model response into the structured Humor Agent result."""
    json_text = _extract_json_text(raw)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise HumorParseError(HumorFallbackReason.INVALID_JSON, str(exc)) from exc

    if not isinstance(data, dict):
        raise HumorParseError(HumorFallbackReason.INVALID_JSON, "top-level JSON is not object")

    missing = [field for field in _REQUIRED_FIELDS if field not in data]
    if missing:
        raise HumorParseError(
            HumorFallbackReason.MISSING_FIELD,
            f"missing fields: {', '.join(missing)}",
        )

    def text_field(name: str) -> str:
        value: Any = data.get(name, "")
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    return HumorRewriteResult(
        user_input=request.user_input,
        normal_response=request.normal_response,
        scene=text_field("scene"),
        emotion=text_field("emotion"),
        humor_anchor=text_field("humor_anchor"),
        worldview_mapping=text_field("worldview_mapping"),
        style=text_field("style"),
        candidate_response=text_field("candidate_response"),
        risk=text_field("risk"),
        accepted=False,
        enabled=True,
    )

