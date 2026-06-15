"""InteractionLearner — B站直播间交互模式学习.

Analyzes danmaku interaction patterns from B站 live rooms to
generate livestream optimization strategies for Anima.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from . import api
from .models import DanmakuMessage, LivestreamStrategy

# ── Wiki data models (local definitions for strategy storage) ──────────


class PageType(Enum):
    """Wiki page type classification."""
    CONCEPT = "concept"
    ENTITY = "entity"
    SOURCE = "source"
    SYNTHESIS = "synthesis"


@dataclass
class WikiPage:
    """A page in the wiki knowledge base."""
    title: str = ""
    page_type: PageType = PageType.CONCEPT
    path: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

logger = logging.getLogger(__name__)


# ── LLM Prompts ─────────────────────────────────────────────────────────

INTERACTION_ANALYSIS_SYSTEM_PROMPT = """你是一个直播互动分析专家。分析B站直播间的弹幕互动数据，提取可操作的直播优化策略。

分析维度：
1. 主播回应频率分布 — 高频互动（秒回）/ 中频互动（选回）/ 低频互动（很少回）
2. 梗使用时机 — 弹幕高潮期 / 冷场期 / 特定话题触发时的梗使用
3. 观众情感流动 — 积极情绪 vs 消极情绪的时间分布
4. 互动类型分类 — 问答型 / 调侃型 / 情感共鸣型 / 信息型

输出要求：严格输出 JSON 格式
{
  "patterns": [
    {
      "name": "模式名称",
      "description": "模式描述",
      "applicable_scenarios": ["场景1", "场景2"],
      "confidence": 0.0-1.0
    }
  ],
  "strategies": [
    {
      "trigger_condition": "触发条件",
      "suggested_behavior": "建议行为",
      "expected_effect": "预期效果",
      "priority": "high/medium/low"
    }
  ],
  "summary": "一句话总结发现的交互模式"
}"""

INTERACTION_ANALYSIS_USER_PROMPT = """分析以下B站直播间的弹幕互动数据：

{room_data}

请进行交互模式分析，输出 JSON。"""


class InteractionLearner:
    """学习B站直播间的弹幕交互模式，生成直播优化策略。

    Pipeline:
    1. Connect to configured B站 live rooms
    2. Collect >= 100 danmaku samples per room
    3. LLM analysis of interaction patterns
    4. Generate actionable strategies → Wiki storage
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        wiki_manager: Any | None = None,
        config: dict[str, Any] | None = None,
    ):
        """
        Args:
            llm_client: LLM client with .chat(messages, **kwargs) method.
            wiki_manager: WikiManager instance for strategy storage.
            config: Optional config dict. Keys:
                - room_ids: list of room IDs to monitor (default [])
                - min_samples_per_room: minimum danmaku per room (default 100)
                - collection_timeout: max collection seconds per room (default 300)
                - request_delay: delay between rooms (default 2.0)
        """
        self._llm = llm_client
        self._wiki = wiki_manager
        self._config = config or {}
        self._room_ids: list[int] = self._config.get("room_ids", [])
        self._min_samples = self._config.get("min_samples_per_room", 100)
        self._collection_timeout = self._config.get("collection_timeout", 300)
        self._request_delay = self._config.get("request_delay", 2.0)

    # ── Public API ──────────────────────────────────────────────────────

    async def learn_patterns(self) -> list[LivestreamStrategy]:
        """Run the full interaction learning pipeline.

        Returns:
            List of generated LivestreamStrategy.
        """
        logger.info(
            "[InteractionLearner] Starting interaction learning "
            "(rooms=%s, min_samples=%d)",
            self._room_ids, self._min_samples,
        )

        if not self._room_ids:
            logger.info("[InteractionLearner] No room IDs configured, skipping")
            return []

        all_samples: dict[int, list[DanmakuMessage]] = {}

        for room_id in self._room_ids:
            try:
                samples = await self._collect_danmaku(room_id)
                if len(samples) >= self._min_samples:
                    all_samples[room_id] = samples
                    logger.info(
                        "[InteractionLearner] Room %d: collected %d samples",
                        room_id, len(samples),
                    )
                else:
                    logger.info(
                        "[InteractionLearner] Room %d: insufficient samples "
                        "(%d < %d), skipping",
                        room_id, len(samples), self._min_samples,
                    )
                await asyncio.sleep(self._request_delay)
            except Exception as e:
                logger.warning(
                    "[InteractionLearner] Failed for room %d: %s", room_id, e,
                )

        if not all_samples:
            logger.info("[InteractionLearner] No rooms with sufficient samples")
            return []

        # Analyze patterns
        strategies = await self._analyze_patterns(all_samples)

        # Store strategies to Wiki
        if strategies and self._wiki:
            await self._store_strategies(strategies)

        return strategies

    async def get_hot_danmaku_phrases(
        self,
        min_freq: int = 3,
        max_phrases: int = 30,
    ) -> list[str]:
        """Collect hot danmaku phrases from configured rooms.

        Useful for the meme collection pipeline to query what's trending
        in live chat without running the full interaction analysis.

        Args:
            min_freq: Minimum occurrence count to consider a phrase hot.
            max_phrases: Maximum number of phrases to return.

        Returns:
            List of hot danmaku phrase texts.
        """
        if not self._room_ids:
            return []

        from collections import Counter
        all_texts: list[str] = []

        for room_id in self._room_ids:
            try:
                texts = await api.fetch_live_danmaku(room_id, limit=self._min_samples)
                for t in texts:
                    if len(t.strip()) >= 2:
                        all_texts.append(t)
                await asyncio.sleep(self._request_delay)
            except Exception as e:
                logger.warning(
                    "[InteractionLearner] Failed to collect danmaku for room %d: %s",
                    room_id, e,
                )

        if not all_texts:
            return []

        # Simple frequency-based phrase extraction
        counter: Counter = Counter()
        for text in all_texts:
            counter[text] += 1

        # Filter by min_freq and return top phrases
        hot = [text for text, count in counter.most_common(max_phrases * 2)
               if count >= min_freq]
        return hot[:max_phrases]

    # ── Danmaku collection ──────────────────────────────────────────────

    async def _collect_danmaku(self, room_id: int) -> list[DanmakuMessage]:
        """Collect danmaku samples from a live room via shared API."""
        start_time = asyncio.get_event_loop().time()

        texts = await api.fetch_live_danmaku(room_id, limit=self._min_samples)

        samples: list[DanmakuMessage] = []
        for t in texts:
            samples.append(DanmakuMessage(text=t))

        elapsed = asyncio.get_event_loop().time() - start_time
        logger.debug(
            "[InteractionLearner] Room %d: %d samples in %.1fs",
            room_id, len(samples), elapsed,
        )
        return samples

    # ── Pattern analysis ────────────────────────────────────────────────

    async def _analyze_patterns(
        self,
        samples_by_room: dict[int, list[DanmakuMessage]],
    ) -> list[LivestreamStrategy]:
        """Use LLM to analyze danmaku interaction patterns."""
        if not self._llm:
            logger.info("[InteractionLearner] No LLM client, skipping analysis")
            return []

        # Build analysis context
        room_sections: list[str] = []
        for room_id, samples in samples_by_room.items():
            # Take a representative sample (first 50 danmaku)
            sample_texts = [s.text for s in samples[:50]]
            section = (
                f"=== 直播间 {room_id} ===\n"
                f"总弹幕数: {len(samples)}\n"
                f"弹幕样本:\n" + "\n".join(f"  - {t}" for t in sample_texts[:30])
            )
            room_sections.append(section)

        combined = "\n\n".join(room_sections)

        try:
            result = await self._llm.chat_messages(
                messages=[
                    {"role": "system", "content": INTERACTION_ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": INTERACTION_ANALYSIS_USER_PROMPT.format(
                        room_data=combined,
                    )},
                ],
                response_format={"type": "json_object"},
            )

            content = result.get("content", "") if isinstance(result, dict) else str(result)
            parsed = self._parse_json(content)

            strategies_raw = parsed.get("strategies", [])
            strategies: list[LivestreamStrategy] = []
            for s in strategies_raw:
                strategies.append(LivestreamStrategy(
                    trigger_condition=s.get("trigger_condition", ""),
                    suggested_behavior=s.get("suggested_behavior", ""),
                    expected_effect=s.get("expected_effect", ""),
                    priority=s.get("priority", "medium"),
                ))

            # Also extract patterns for logging
            patterns_raw = parsed.get("patterns", [])
            for p in patterns_raw:
                logger.info(
                    "[InteractionLearner] Pattern: %s (confidence=%.2f)",
                    p.get("name", "unknown"), p.get("confidence", 0.5),
                )

            summary = parsed.get("summary", "")
            if summary:
                logger.info("[InteractionLearner] Summary: %s", summary)

            return strategies

        except Exception as e:
            logger.warning("[InteractionLearner] LLM analysis failed: %s", e)
            return []

    # ── Strategy storage ────────────────────────────────────────────────

    async def _store_strategies(self, strategies: list[LivestreamStrategy]) -> None:
        """Store strategies as a Wiki page for retrieval."""
        if not self._wiki:
            return

        try:
            content_lines = [
                "# 直播优化策略",
                "",
                f"**生成时间**: {datetime.now().isoformat()}",
                f"**策略数**: {len(strategies)}",
                "",
                "## 策略列表",
                "",
            ]

            for i, s in enumerate(strategies, 1):
                content_lines.append(f"### {i}. [{s.priority.upper()}] {s.trigger_condition}")
                content_lines.append(f"- **建议行为**: {s.suggested_behavior}")
                content_lines.append(f"- **预期效果**: {s.expected_effect}")
                content_lines.append(f"- **优先级**: {s.priority}")
                content_lines.append("")

            content = "\n".join(content_lines)

            page = WikiPage(
                title=f"直播优化策略 {datetime.now().strftime('%Y-%m-%d')}",
                page_type=PageType.CONCEPT,
                path=f"concepts/livestream-strategy-{datetime.now().strftime('%Y%m%d')}.md",
                content=content,
                tags=["livestream", "optimization", "bilibili", datetime.now().strftime("%Y-%m-%d")],
                links=[],
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            self._wiki.write_page(page)
            logger.info(
                "[InteractionLearner] Stored %d strategies to Wiki: %s",
                len(strategies), page.path,
            )
        except Exception as e:
            logger.warning(
                "[InteractionLearner] Failed to store strategies: %s", e,
            )

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Parse LLM JSON response."""
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {}
