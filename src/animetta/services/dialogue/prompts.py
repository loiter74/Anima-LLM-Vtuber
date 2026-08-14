"""Explicit message builders for the isolated two-pass LLM calls."""

from __future__ import annotations

import json

from .models import ComposerRequest, ReasonerRequest

_REASONER_SCHEMA = (
    "Return only strict JSON with exactly these string fields: "
    '{"normal_response":"usable direct answer","stance":"position or attitude",'
    '"humor":"optional direction","worldview":"optional Anima-world mapping"}. '
    "All four keys are required. Do not use markdown fences or runtime markers."
)
_COMPOSER_SCHEMA = (
    'Return only strict JSON with exactly: {"final_response":"single viewer-facing answer",'
    '"mood":"neutral|bright|tired|irritated","affinity_delta":0}. '
    "affinity_delta must be an integer from -2 to 2. Do not use markdown fences or runtime markers."
)


def _window_messages(window: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for user, assistant in window[-6:]:
        messages.extend(
            (
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            )
        )
    return messages


def build_reasoner_messages(request: ReasonerRequest) -> list[dict[str, str]]:
    system = "\n\n".join(
        part
        for part in (request.persona_prompt, request.roleplay_correction, _REASONER_SCHEMA)
        if part
    )
    payload = {
        "user_input": request.user_input,
    }
    return [
        {"role": "system", "content": system},
        *_window_messages(request.completed_window),
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def build_composer_messages(request: ComposerRequest) -> list[dict[str, str]]:
    system = "\n\n".join(
        part
        for part in (request.persona_prompt, request.roleplay_correction, _COMPOSER_SCHEMA)
        if part
    )
    payload = {
        "user_input": request.user_input,
        "reasoner": request.reasoner.model_dump(),
        "state": {
            "mood": request.mood,
            "fatigue": request.fatigue,
            "affinity": request.affinity,
        },
    }
    return [
        {"role": "system", "content": system},
        *_window_messages(request.completed_window),
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]
