"""History-neutral Reasoner and AnimaComposer services."""

from __future__ import annotations

import asyncio

from animetta.services.humor.history_safe import has_native_chat_messages
from animetta.services.llm.interface import LLMInterface

from .contracts import (
    ComposerResult,
    DialogueParseError,
    ReasonerResult,
    parse_composer_result,
    parse_reasoner_result,
)
from .models import ComposerRequest, ReasonerRequest
from .prompts import build_composer_messages, build_reasoner_messages


class DialogueServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Reasoner:
    def __init__(self, llm: LLMInterface, *, timeout_seconds: float = 30.0) -> None:
        self.llm = llm
        self.timeout_seconds = timeout_seconds

    async def reason(self, request: ReasonerRequest) -> ReasonerResult:
        raw = await _isolated_call(
            self.llm, build_reasoner_messages(request), self.timeout_seconds
        )
        try:
            return parse_reasoner_result(raw)
        except DialogueParseError as exc:
            raise DialogueServiceError(exc.code) from exc


class AnimaComposer:
    def __init__(self, llm: LLMInterface, *, timeout_seconds: float = 30.0) -> None:
        self.llm = llm
        self.timeout_seconds = timeout_seconds

    async def compose(self, request: ComposerRequest) -> ComposerResult:
        raw = await _isolated_call(
            self.llm, build_composer_messages(request), self.timeout_seconds
        )
        try:
            return parse_composer_result(raw)
        except DialogueParseError as exc:
            raise DialogueServiceError(exc.code) from exc


async def _isolated_call(
    llm: LLMInterface, messages: list[dict[str, str]], timeout_seconds: float
) -> str:
    if not has_native_chat_messages(llm):
        raise DialogueServiceError("history_unsafe")
    try:
        async with asyncio.timeout(timeout_seconds):
            return await llm.chat_messages(
                messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
    except TimeoutError as exc:
        raise DialogueServiceError("timeout") from exc
    except DialogueServiceError:
        raise
    except Exception as exc:
        raise DialogueServiceError("provider_error") from exc
