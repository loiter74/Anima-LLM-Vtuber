"""Anima Humor Agent pipeline."""

from __future__ import annotations

import asyncio
import time

from loguru import logger

from animetta.services.llm.interface import LLMInterface

from .config import HumorConfig
from .filters import validate_humor_candidate
from .history_safe import chat_messages_history_safe
from .models import (
    HumorFallbackReason,
    HumorRewriteRequest,
    HumorRewriteResult,
    fallback_result,
)
from .parser import HumorParseError, parse_humor_result
from .prompts import build_humor_messages


class HumorAgent:
    """Pipeline that rewrites normal replies into Anima-style humor."""

    def __init__(
        self,
        llm: LLMInterface,
        config: HumorConfig | None = None,
    ) -> None:
        self.llm = llm
        self.config = config or HumorConfig()

    async def rewrite(self, request: HumorRewriteRequest) -> HumorRewriteResult:
        """Rewrite a normal response or return a structured fallback."""
        result = await self.generate_candidate(request)
        if result.fallback_reason:
            return result

        config = request.config or self.config
        rejection = validate_humor_candidate(result, config)
        if rejection:
            return result.reject(rejection)
        return result.accept()

    async def generate_candidate(self, request: HumorRewriteRequest) -> HumorRewriteResult:
        """Generate a structured humor candidate without accepting or rejecting it."""
        config = request.config or self.config
        started = time.perf_counter()

        if not config.enabled:
            return fallback_result(
                request,
                HumorFallbackReason.DISABLED,
                enabled=False,
            )
        if not request.normal_response.strip():
            return fallback_result(request, HumorFallbackReason.NO_NORMAL_RESPONSE)

        messages = build_humor_messages(request, config)
        try:
            async with asyncio.timeout(config.timeout_seconds):
                internal = await chat_messages_history_safe(self.llm, messages)
        except TimeoutError:
            return fallback_result(
                request,
                HumorFallbackReason.LLM_TIMEOUT,
                duration_ms=_elapsed_ms(started),
            )
        except Exception as exc:
            logger.warning(f"[HumorAgent] Internal LLM call failed: {exc}")
            return fallback_result(
                request,
                HumorFallbackReason.LLM_ERROR,
                duration_ms=_elapsed_ms(started),
            )

        if internal.fallback_reason:
            return fallback_result(
                request,
                internal.fallback_reason,
                duration_ms=_elapsed_ms(started),
            )

        try:
            result = parse_humor_result(internal.content or "", request)
        except HumorParseError as exc:
            return fallback_result(
                request,
                exc.reason,
                duration_ms=_elapsed_ms(started),
            )

        result.duration_ms = _elapsed_ms(started)
        return result


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
