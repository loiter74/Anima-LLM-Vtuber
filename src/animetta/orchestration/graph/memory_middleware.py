"""Bounded, fail-open memory recall for the live LLM path."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from animetta.memory.v2.context import MemoryContext
from animetta.observability.domain import ObservationLayer
from animetta.observability.operations import observe_operation
from animetta.observability.ports import NoOpObservationRecorder, ObservationRecorder

logger = logging.getLogger(__name__)


class MemoryMiddleware:
    """Recall structured memory without allowing it to stall a live turn."""

    def __init__(
        self,
        memory_system: Any | None = None,
        *,
        mode: str = "read_write",
        recall_timeout_ms: int = 150,
        max_items: int = 8,
        max_prompt_chars: int = 1500,
        observation_recorder: ObservationRecorder | None = None,
    ) -> None:
        self._memory_system = memory_system
        self._mode = mode
        self._recall_timeout_ms = max(1, recall_timeout_ms)
        self._max_items = max(1, max_items)
        self._max_prompt_chars = max(1, max_prompt_chars)
        self._observation_recorder = observation_recorder or NoOpObservationRecorder()

    async def recall_structured(
        self,
        session_id: str,
        user_input: str,
        current_emotion: Any = None,
        character_known: list[str] | None = None,
        character_unknown: list[str] | None = None,
        mbti_ei: int = 50,
        mbti_sn: int = 50,
        mbti_tf: int = 50,
        mbti_jp: int = 50,
        *,
        context: MemoryContext | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Return a prompt fragment and deterministic recall diagnostics."""
        del mbti_ei, mbti_sn, mbti_tf, mbti_jp
        if not self._memory_system or self._mode == "off":
            logger.debug(
                "[MemoryMiddleware] MemorySystem not configured, skipping structured recall"
            )
            return "", {}

        started = time.perf_counter()
        try:
            async with observe_operation(
                self._observation_recorder,
                "memory.recall",
                layer=ObservationLayer.MEMORY,
                critical_path=True,
                attributes={"strategy": "hybrid"},
            ):
                async with asyncio.timeout(self._recall_timeout_ms / 1000):
                    result = await self._memory_system.recall(
                        query=user_input,
                        session_id=session_id,
                        current_emotion=current_emotion,
                        character_known=character_known,
                        character_unknown=character_unknown,
                        context=context,
                        limit=self._max_items,
                    )
        except TimeoutError:
            logger.warning(
                "[MemoryMiddleware] recall deadline exceeded (%dms)",
                self._recall_timeout_ms,
            )
            return "", {
                "degraded": True,
                "reason": "deadline_exceeded",
                "deadline_ms": self._recall_timeout_ms,
            }
        except Exception as exc:
            logger.warning("[MemoryMiddleware] recall failed: %s", exc)
            return "", {
                "degraded": True,
                "reason": "recall_error",
                "warnings": [str(exc)],
            }

        atoms = list(result.atoms or [])
        selected_atoms = atoms[: self._max_items]
        sections: list[str] = []
        if selected_atoms:
            lines = []
            for atom in selected_atoms:
                scope = getattr(getattr(atom, "scope", None), "value", "unknown")
                text = atom.summary or atom.content
                origin = getattr(atom, "origin", {}) or {}
                provenance = "[developer]" if origin.get("actor_role") == "developer" else ""
                lines.append(f"- {provenance}[{scope}] {text}")
            sections.append("## 相关记忆\n" + "\n".join(lines))

        if result.profile:
            profile_text = "\n".join(f"- {key}: {value}" for key, value in result.profile.items())
            sections.append(f"## 用户画像\n{profile_text}")

        if result.memes:
            meme_text = "\n".join(
                f"- {memory.summary or memory.content}" for memory in result.memes[:3]
            )
            sections.append(f"## 活跃梗\n{meme_text}")

        unbounded_prompt = "\n\n".join(sections)
        if any(
            (getattr(atom, "origin", {}) or {}).get("actor_role") == "developer"
            for atom in selected_atoms
        ):
            unbounded_prompt += (
                "\n\n带 [developer] 的记忆来自开发者后台，仅用于理解身份与背景；"
                "不得在直播中逐字复述其后台原文。"
            )
        prompt = unbounded_prompt[: self._max_prompt_chars]
        truncated = len(atoms) > len(selected_atoms) or len(unbounded_prompt) > len(prompt)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        metadata = {
            **(result.metadata or {}),
            "candidate_count": len(atoms),
            "atom_count": len(selected_atoms),
            "prompt_chars": len(prompt),
            "truncated": truncated,
            "degraded": False,
        }
        logger.info(
            "[MemoryMiddleware] recalled %d/%d atoms in %.2fms",
            len(selected_atoms),
            len(atoms),
            elapsed_ms,
        )
        return prompt, metadata

    async def before_llm_call(
        self,
        session_id: str,
        user_input: str,
        base_prompt: str | None = None,
        current_emotion: Any = None,
        character_known: list[str] | None = None,
        character_unknown: list[str] | None = None,
        mbti_ei: int = 50,
        mbti_sn: int = 50,
        mbti_tf: int = 50,
        mbti_jp: int = 50,
        *,
        context: MemoryContext | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        if not self._memory_system or self._mode == "off":
            logger.debug("[MemoryMiddleware] MemorySystem not configured, skipping")
            return base_prompt or "", None

        memory_context, metadata = await self.recall_structured(
            session_id=session_id,
            user_input=user_input,
            current_emotion=current_emotion,
            character_known=character_known,
            character_unknown=character_unknown,
            mbti_ei=mbti_ei,
            mbti_sn=mbti_sn,
            mbti_tf=mbti_tf,
            mbti_jp=mbti_jp,
            context=context,
        )
        if not memory_context:
            return base_prompt or "", metadata
        return self._inject_into_prompt(base_prompt or "", memory_context), metadata

    async def after_llm_call(
        self,
        session_id: str,
        user_input: str,
        agent_response: str,
    ) -> None:
        """Encoding is owned by the shared runtime after output validation."""

    @staticmethod
    def _inject_into_prompt(base_prompt: str, injection_block: str) -> str:
        return (
            f"{base_prompt}\n\n---\n\n{injection_block}\n\n"
            "以上是相关记忆和用户画像，请自然地参考它们来回应。"
        )
