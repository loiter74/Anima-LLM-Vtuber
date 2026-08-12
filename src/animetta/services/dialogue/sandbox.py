"""Private Dashboard dialogue sandbox with no live-output side effects."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from animetta.services.llm.interface import LLMInterface
from animetta.services.llm.internal_calls import has_native_chat_messages


class SandboxConversationError(RuntimeError):
    """A bounded, user-safe sandbox failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SandboxTurn:
    role: str
    content: str


class SandboxConversationService:
    """Invoke the active LLM with explicit, history-neutral private context."""

    def __init__(self, llm: LLMInterface, *, timeout_seconds: float = 30.0) -> None:
        self.llm = llm
        self.timeout_seconds = timeout_seconds

    async def stream(
        self,
        text: str,
        history: Sequence[SandboxTurn] = (),
        *,
        system_prompt: str,
    ) -> AsyncIterator[str]:
        if not has_native_chat_messages(self.llm):
            raise SandboxConversationError("history_unsafe")
        messages = [
            {"role": "system", "content": system_prompt},
            *({"role": turn.role, "content": turn.content} for turn in history),
            {"role": "user", "content": text},
        ]
        try:
            emitted = False
            async with asyncio.timeout(self.timeout_seconds):
                async for chunk in self.llm.chat_messages_stream(messages):
                    if chunk:
                        emitted = True
                        yield chunk
            if not emitted:
                raise SandboxConversationError("empty_response")
        except TimeoutError as exc:
            raise SandboxConversationError("timeout") from exc
        except asyncio.CancelledError:
            raise
        except SandboxConversationError:
            raise
        except Exception as exc:
            raise SandboxConversationError("provider_error") from exc
