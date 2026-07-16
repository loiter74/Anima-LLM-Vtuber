"""ReconsolidationClient — lightweight LLM client for memory rewriting.

Bypasses the full animetta service chain to avoid import cascades.
Uses openai package directly (already a project dependency).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Try importing openai; fall back gracefully
try:
    from openai import AsyncOpenAI

    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    AsyncOpenAI = None  # type: ignore[assignment, misc]


@dataclass
class ReconsolidationOutput:
    """Result of a reconsolidation LLM call."""

    summary: str  # Rewritten memory summary
    confidence_delta: float  # Change to confidence (-0.1 to +0.1)
    emotion_shift: tuple[float, float, float]  # VAD shift (valence, arousal, dominance)


RECONSOLIDATION_PROMPT = """你是 Animetta 的记忆系统。你正在"回忆"一段记忆。

【原始记忆】（版本 {version}，上次改写于 {rewritten_at}）
{content}

【当前语境】
- 对话主题: {dialogue_topic}
- 当前情绪: V={valence:.2f}, A={arousal:.2f}, D={dominance:.2f}
- 检索原因: {query}

【任务】
用当前语境的视角重新表达这段记忆。规则：
1. 核心事实不可改变（"用户喜欢咖啡"不能变成"用户喜欢茶"）
2. 语气和措辞可以被当前情绪染色（轻松愉快 → 更口语化；低落 → 更克制）
3. 如果当前语境和记忆有关联，自然地强化这种关联
4. 长度不超过原文的 120%
5. 如果记忆已经历多次重述（version > 5），可以适度融入旧版本的"口吻"

输出 JSON:
{{"summary": "...", "confidence_delta": 0.05, "emotion_shift": [0.1, 0.0, -0.05]}}"""


class ReconsolidationClient:
    """Lightweight LLM client for memory reconsolidation.

    Usage:
        client = ReconsolidationClient(api_key="sk-...", base_url="...")
        result = await client.reconsolidate(
            content="用户喜欢咖啡",
            version=3,
            rewritten_at="2026-05-30",
            valence=0.6, arousal=0.3, dominance=0.1,
            query="咖啡推荐",
            dialogue_topic="下午茶",
        )
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
    ):
        self.model = model
        self._client: Any = None

        if _HAS_OPENAI and api_key:
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
            )

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def reconsolidate(
        self,
        content: str,
        version: int,
        rewritten_at: str,
        valence: float,
        arousal: float,
        dominance: float,
        query: str = "",
        dialogue_topic: str = "",
    ) -> ReconsolidationOutput | None:
        """Call LLM to rewrite a memory through reconsolidation.

        Returns None if LLM is unavailable or call fails.
        """
        if not self._client:
            return None

        prompt = RECONSOLIDATION_PROMPT.format(
            content=content,
            version=version,
            rewritten_at=rewritten_at,
            valence=valence,
            arousal=arousal,
            dominance=dominance,
            query=query,
            dialogue_topic=dialogue_topic or "日常对话",
        )

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个记忆重述系统。只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            text = response.choices[0].message.content
            data = json.loads(text)

            shift = data.get("emotion_shift", [0.0, 0.0, 0.0])
            return ReconsolidationOutput(
                summary=data.get("summary", content),
                confidence_delta=data.get("confidence_delta", 0.0),
                emotion_shift=(
                    float(shift[0]) if len(shift) > 0 else 0.0,
                    float(shift[1]) if len(shift) > 1 else 0.0,
                    float(shift[2]) if len(shift) > 2 else 0.0,
                ),
            )

        except Exception as e:
            logger.warning(f"Reconsolidation LLM call failed: {e}")
            return None


# Singleton for easy access
_reconsolidation_client: ReconsolidationClient | None = None


def get_reconsolidation_client() -> ReconsolidationClient | None:
    return _reconsolidation_client


def set_reconsolidation_client(client: ReconsolidationClient | None) -> None:
    global _reconsolidation_client
    _reconsolidation_client = client
