"""
Memory middleware: automatically handles memory before and after LLM calls.

V2: Uses LivingMemorySystem.recall() for unified retrieval —
replaces FuzzyLayer + UserProfile + MemePool with a single call.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MemoryMiddleware:
    """Automatic memory injection middleware — V2 unified recall()."""

    def __init__(self, memory_system: Any | None = None):
        self._memory_system = memory_system

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
    ) -> tuple[str, dict[str, Any]]:
        """Structured recall: returns memory context text and metadata.

        Unlike ``before_llm_call``, this method does NOT inject memory
        into a system prompt. The prompt pipeline owns final assembly.

        Returns: (memory_context_text, metadata_dict).
        """
        if not self._memory_system:
            logger.debug("[MemoryMiddleware] MemorySystem not configured, skipping structured recall")
            return "", {}

        metadata: dict[str, Any] = {}
        injection_parts: list[str] = []

        try:
            result = await self._memory_system.recall(
                query=user_input,
                session_id=session_id,
                current_emotion=current_emotion,
                character_known=character_known,
                character_unknown=character_unknown,
                mbti_ei=mbti_ei,
                mbti_sn=mbti_sn,
                mbti_tf=mbti_tf,
                mbti_jp=mbti_jp,
            )
        except Exception as e:
            logger.warning(f"[MemoryMiddleware] structured recall() failed: {e}")
            metadata["warnings"] = [f"recall failed: {e}"]
            return "", metadata

        atom_count = 0
        if result.atoms:
            atom_count = len(result.atoms)
            summaries = [a.summary or a.content for a in result.atoms[:5]]
            injection_parts.append(
                "## 相关记忆\n" + "\n".join(f"- {s}" for s in summaries)
            )

        if result.profile:
            profile_text = "\n".join(
                f"- {k}: {v}" for k, v in result.profile.items()
            )
            injection_parts.append(f"## 用户画像\n{profile_text}")

        if result.memes:
            meme_text = "\n".join(
                f"- {m.summary or m.content}" for m in result.memes[:3]
            )
            injection_parts.append(f"## 活跃梗\n{meme_text}")

        memory_context = "\n\n".join(injection_parts) if injection_parts else ""
        metadata["atom_count"] = atom_count

        logger.info(f"[MemoryMiddleware] structured recall: {atom_count} atoms")
        return memory_context, metadata

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
    ) -> tuple[str, dict | None]:
        """Before LLM call: retrieve memory via LivingMemorySystem.recall().

        Args:
            session_id: Current session identifier.
            user_input: User's message text.
            base_prompt: System prompt to enrich with memory.
            current_emotion: Current VAD emotion vector.
            character_known: Character's known knowledge domains (for filtering).
            character_unknown: Character's unknown knowledge domains (excluded from recall).
            mbti_ei, mbti_sn, mbti_tf, mbti_jp: MBTI dimensions for persona-biased ranking.

        Returns: (enriched_prompt, metadata_dict).
        """
        if not self._memory_system:
            logger.debug("[MemoryMiddleware] MemorySystem not configured, skipping")
            return base_prompt or "", None

        metadata: dict[str, Any] = {}
        injection_parts: list[str] = []

        try:
            result = await self._memory_system.recall(
                query=user_input,
                session_id=session_id,
                current_emotion=current_emotion,
                character_known=character_known,
                character_unknown=character_unknown,
                mbti_ei=mbti_ei,
                mbti_sn=mbti_sn,
                mbti_tf=mbti_tf,
                mbti_jp=mbti_jp,
            )
        except Exception as e:
            logger.warning(f"[MemoryMiddleware] recall() failed: {e}")
            return base_prompt or "", metadata

        # Build injection from unified result
        if result.atoms:
            summaries = [
                a.summary or a.content for a in result.atoms[:5]
            ]
            injection_parts.append(
                "## 相关记忆\n" + "\n".join(f"- {s}" for s in summaries)
            )

        if result.profile:
            profile_text = "\n".join(
                f"- {k}: {v}" for k, v in result.profile.items()
            )
            injection_parts.append(f"## 用户画像\n{profile_text}")

        if result.memes:
            meme_text = "\n".join(
                f"- {m.summary or m.content}" for m in result.memes[:3]
            )
            injection_parts.append(f"## 活跃梗\n{meme_text}")

        if not injection_parts:
            logger.debug("[MemoryMiddleware] no memory to inject")
            return base_prompt or "", metadata

        injection_block = "\n\n".join(injection_parts)
        enriched = self._inject_into_prompt(base_prompt or "", injection_block)

        logger.info(f"[MemoryMiddleware] injected {len(result.atoms)} atoms")
        return enriched, metadata

    async def after_llm_call(
        self,
        session_id: str,
        user_input: str,
        agent_response: str,
    ) -> None:
        """After LLM call: no-op. Encoding handled by output_node."""
        pass

    @staticmethod
    def _inject_into_prompt(base_prompt: str, injection_block: str) -> str:
        """Inject memory content into system prompt."""
        return (
            f"{base_prompt}\n\n---\n\n{injection_block}\n\n"
            "以上是相关记忆和用户画像，请自然地参考它们来回应。"
        )
