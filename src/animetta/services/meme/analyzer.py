"""MemeCognitiveAnalyzer — LLM 驱动的梗认知分析管道.

Analyzes meme candidates using cognitive science frameworks:
humor mechanism, context trigger, emotional tone, persona fit.
Outputs structured CognitiveAnalysis for Meme model.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Data models ────────────────────────────────────────────────────────


class CognitiveAnalysis(dict):
    """Structured cognitive analysis result for a meme candidate.

    Subclasses dict so that ``isinstance(result, dict)`` remains True
    while allowing attribute-style access (``result.humor_mechanism``).
    """

    def __init__(
        self,
        *,
        humor_mechanism: str = "",
        context_trigger: str = "",
        emotional_tone: str = "",
        persona_fit_score: float = 0.0,
        usage_example: str = "",
        source_url: str = "",
    ) -> None:
        super().__init__(
            humor_mechanism=humor_mechanism,
            context_trigger=context_trigger,
            emotional_tone=emotional_tone,
            persona_fit_score=persona_fit_score,
            usage_example=usage_example,
            source_url=source_url,
        )

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


@dataclass
class Meme:
    """A meme entry stored in the MemePool."""

    id: str = ""
    text: str = ""
    context_hint: str = ""
    confidence: float = 0.0
    tags: list[str] = field(default_factory=list)
    cognitive_analysis: CognitiveAnalysis | None = None
    source_platform: str = ""
    created_at: float = field(default_factory=time.time)


class MemePool:
    """Pool for storing and retrieving memes."""

    def __init__(self, store: Any | None = None) -> None:
        self.store = store

    def add_from_candidate(
        self,
        text: str,
        context_hint: str = "",
        confidence: float = 0.0,
        tags: list[str] | None = None,
    ) -> Meme | None:
        """Create and store a Meme from a candidate string."""
        meme = Meme(
            id=f"meme_{hash(text) & 0xFFFFFFFF:08x}",
            text=text,
            context_hint=context_hint,
            confidence=confidence,
            tags=tags or [],
        )
        if self.store is not None:
            self.store.update(meme)
        return meme



# ── LLM Prompt for cognitive analysis ─────────────────────────────────

COGNITIVE_ANALYSIS_SYSTEM_PROMPT = """你是一个认知科学和网络文化分析专家。分析网络梗（meme）的认知机制和使用特征。

你的角色设定：
- 你为 AI VTuber (虚拟主播) 分析梗，人设是理性主导、冷幽默风格的 AI
- 分析梗时关注：这个梗为什么好笑/有趣？在什么情境下使用？传达什么情感？

输出要求：
- 严格输出 JSON 格式，不要有任何额外文字
- 所有字段必填，没有的信息用空字符串或默认值

JSON Schema:
{
  "humor_mechanism": "梗的幽默机制（选择: 双关/反讽/荒诞/自指/谐音/反差/夸张/其他）",
  "context_trigger": "触发使用该梗的具体对话场景描述（如：当用户抱怨某件事时，当讨论某个话题时）",
  "emotional_tone": "梗传达的情感色彩（选择: 幽默/讽刺/自嘲/温暖/荒诞/吐槽/其他）",
  "persona_fit_score": 0.0-1.0 的浮点数，表示这个梗与'理性、冷幽默 AI VTuber'人设的匹配程度。理性分析型梗得分高（0.7+），纯搞笑无深度的梗得分低（<0.5），不符合人设风格的梗得分低，
  "usage_example": "在对话中使用这个梗的具体示例（10-30字，符合AI VTuber的语气）"
}"""

COGNITIVE_ANALYSIS_USER_PROMPT = """请分析以下网络梗：

梗文本: {text}
使用场景提示: {context_hint}
来源: {source}
标签: {tags}

请进行认知分析，输出 JSON。"""

# Required fields for validation
REQUIRED_FIELDS = [
    "humor_mechanism",
    "context_trigger",
    "emotional_tone",
    "persona_fit_score",
    "usage_example",
]


class MemeCognitiveAnalyzer:
    """LLM 驱动的梗认知分析器.

    Takes raw meme text and context, produces structured CognitiveAnalysis.
    Integrates with MemePool for ingestion.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        meme_pool: MemePool | None = None,
        config: dict[str, Any] | None = None,
    ):
        """
        Args:
            llm_client: LLM client with .chat(messages, **kwargs) method.
            meme_pool: Optional MemePool for direct ingestion.
            config: Optional config dict. Keys:
                - min_persona_fit_score: threshold for ingestion (default 0.5)
                - system_prompt: override default system prompt
        """
        self._llm = llm_client
        self._meme_pool = meme_pool
        self._config = config or {}
        self._min_persona_fit_score = self._config.get("min_persona_fit_score", 0.4)

    # ── Public API ──────────────────────────────────────────────────────

    async def analyze(
        self,
        text: str,
        context_hint: str = "",
        source: str = "bilibili",
        tags: list[str] | None = None,
        source_url: str = "",
    ) -> CognitiveAnalysis | None:
        """Analyze a single meme candidate and return structured cognitive analysis.

        Returns None if LLM analysis fails.
        """
        if not self._llm:
            logger.debug("[MemeCognitiveAnalyzer] No LLM client, returning basic analysis")
            return self._basic_analysis(text, context_hint)

        # Determine LLM interface: prefer chat_messages, fall back to chat
        system_content = COGNITIVE_ANALYSIS_SYSTEM_PROMPT
        user_content = COGNITIVE_ANALYSIS_USER_PROMPT.format(
            text=text,
            context_hint=context_hint or "通用场景",
            source=source,
            tags=", ".join(tags) if tags else "无",
        )

        try:
            if hasattr(self._llm, 'chat_messages'):
                result = await self._llm.chat_messages(
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_content},
                    ],
                    response_format={"type": "json_object"},
                )
            elif hasattr(self._llm, 'chat'):
                logger.debug("[MemeCognitiveAnalyzer] Using chat() fallback for LLM call")
                combined = system_content + "\n\n" + user_content
                result = await self._llm.chat(
                    messages=[{"role": "user", "content": combined}],
                    response_format={"type": "json_object"},
                )
            else:
                logger.warning(
                    "[MemeCognitiveAnalyzer] LLM has neither chat_messages nor chat()"
                )
                return self._basic_analysis(text, context_hint, source_url)

            content = result.get("content", "") if isinstance(result, dict) else str(result)
            parsed = self._parse_json(content)

            if not self._validate_analysis(parsed):
                logger.warning(
                    "[MemeCognitiveAnalyzer] Invalid analysis for '%s', using basic fallback",
                    text[:30],
                )
                return self._basic_analysis(text, context_hint, source_url)

            analysis = CognitiveAnalysis(
                humor_mechanism=parsed.get("humor_mechanism", ""),
                context_trigger=parsed.get("context_trigger", context_hint),
                emotional_tone=parsed.get("emotional_tone", ""),
                persona_fit_score=float(parsed.get("persona_fit_score", 0.5)),
                usage_example=parsed.get("usage_example", ""),
                source_url=source_url,
            )
            logger.info(
                "[MemeCognitiveAnalyzer] Analyzed '%s': mechanism=%s, fit=%.2f",
                text[:30], analysis.humor_mechanism, analysis.persona_fit_score,
            )
            return analysis

        except Exception as e:
            logger.warning("[MemeCognitiveAnalyzer] LLM analysis failed: %s", e)
            return self._basic_analysis(text, context_hint, source_url)

    async def analyze_and_ingest(
        self,
        text: str,
        context_hint: str = "",
        tags: list[str] | None = None,
        source_url: str = "",
    ) -> Meme | None:
        """Analyze a meme candidate and ingest into MemePool if confidence is sufficient.

        Returns the created Meme if ingested, None if rejected.
        """
        analysis = await self.analyze(
            text=text,
            context_hint=context_hint,
            source="bilibili",
            tags=tags,
            source_url=source_url,
        )

        if analysis is None:
            # Analysis failed, create bare meme with basic fields
            if self._meme_pool:
                return self._meme_pool.add_from_candidate(
                    text=text,
                    context_hint=context_hint,
                    confidence=0.4,
                    tags=tags,
                )
            return None

        if analysis.persona_fit_score < self._min_persona_fit_score:
            logger.info(
                "[MemeCognitiveAnalyzer] Meme rejected (low persona fit %.2f): '%s'",
                analysis.persona_fit_score, text[:30],
            )
            return None

        if self._meme_pool:
            meme = self._meme_pool.add_from_candidate(
                text=text,
                context_hint=analysis.context_trigger or context_hint,
                confidence=analysis.persona_fit_score,
                tags=(tags or []) + [f"mechanism:{analysis.humor_mechanism}"],
            )
            if meme:
                meme.cognitive_analysis = analysis
                meme.source_platform = "bilibili"
                meme.tags = list(set(meme.tags))
                # Update the stored meme with cognitive analysis
                self._meme_pool.store.update(meme)
                logger.info(
                    "[MemeCognitiveAnalyzer] Ingested meme '%s' with fit=%.2f",
                    meme.id, analysis.persona_fit_score,
                )
                return meme

        return None

    # ── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Parse LLM JSON response with markdown fence stripping."""
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
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("[MemeCognitiveAnalyzer] JSON parse error: %s", e)
            return {}

    @staticmethod
    def _validate_analysis(data: dict[str, Any]) -> bool:
        """Validate that all required fields are present."""
        if not data:
            return False
        for required_field in REQUIRED_FIELDS:
            if required_field not in data:
                return False
        # Validate persona_fit_score range
        try:
            score = float(data.get("persona_fit_score", 0))
            if score < 0.0 or score > 1.0:
                return False
        except (ValueError, TypeError):
            return False
        return True

    @staticmethod
    def _basic_analysis(
        text: str,
        context_hint: str = "",
        source_url: str = "",
    ) -> CognitiveAnalysis:
        """Create a basic CognitiveAnalysis without LLM (degraded mode)."""
        return CognitiveAnalysis(
            humor_mechanism="",
            context_trigger=context_hint,
            emotional_tone="",
            persona_fit_score=0.5,
            usage_example="",
            source_url=source_url,
        )
