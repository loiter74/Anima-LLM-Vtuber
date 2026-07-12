"""CompileEngine — RAW → EPISODIC → SEMANTIC → EMERGENT layer progression.

Transforms conversation atoms upward through abstraction layers using LLM.
Lower layers need more atoms to trigger compilation, higher layers consolidate.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from animetta.memory.v2.atom import (
    Layer,
    MemoryAtom,
    MemoryScope,
    Relation,
    RelationType,
)

logger = logging.getLogger(__name__)


@dataclass
class CompileTrigger:
    """When to trigger a compilation pass."""
    min_atoms: int           # Minimum RAW atoms needed
    min_age_hours: float     # Minimum age of oldest atom
    target_layer: Layer      # What layer to produce


# ── Layer progression triggers ──
COMPILE_TRIGGERS: dict[Layer, CompileTrigger] = {
    Layer.RAW: CompileTrigger(
        min_atoms=5,          # 5 conversations → compile to episode
        min_age_hours=1.0,    # At least 1 hour old
        target_layer=Layer.EPISODIC,
    ),
    Layer.EPISODIC: CompileTrigger(
        min_atoms=3,          # 3 episodes → digest to knowledge
        min_age_hours=24.0,   # At least 1 day old
        target_layer=Layer.SEMANTIC,
    ),
    Layer.SEMANTIC: CompileTrigger(
        min_atoms=5,          # 5 knowledge items → emerge meme/synthesis
        min_age_hours=72.0,   # At least 3 days old
        target_layer=Layer.EMERGENT,
    ),
}


COMPILE_SYSTEM_PROMPT = """你是 Animetta 的记忆消化系统。你的任务是将多个零散的原始记忆消化成一个更精炼的上层记忆。

【原始记忆】
{raw_memories}

【任务】
从以上原始记忆中提取核心信息，创建一条精炼的{target_layer_name}。
规则：
1. 合并重复或相似的信息
2. 提取跨时间的模式和行为趋势
3. 保留情感色彩（用户是开心还是难过）
4. 长度控制在原文总长度的 30-50%
5. 输出 JSON 格式

输出 JSON:
{{"summary": "...", "tags": ["标签1", "标签2"]}}"""


class CompileEngine:
    """Handles upward compilation of memory atoms through abstraction layers.

    Called periodically by MetabolismScheduler or on-demand.
    Uses LLM (via llm_call callback) for content transformation.
    """

    def __init__(self, llm_call: Callable | None = None):
        """Initialize with an optional LLM call function.

        Args:
            llm_call: async function (system_prompt, user_prompt) -> str | None
                      If None, uses rule-based fallback (no LLM).
        """
        self._llm_call = llm_call

    async def compile_layer(
        self,
        source_atoms: list[MemoryAtom],
        target_layer: Layer,
    ) -> MemoryAtom | None:
        """Compile multiple source atoms into one target layer atom.

        Args:
            source_atoms: Atoms from the source layer (must all be same layer)
            target_layer: Target layer to create

        Returns:
            New MemoryAtom or None if compilation fails / insufficient data
        """
        if len(source_atoms) < 2:
            return None

        if not all(a.layer.value < target_layer.value for a in source_atoms):
            return None

        boundary = self.boundary_key(source_atoms[0])
        if any(self.boundary_key(atom) != boundary for atom in source_atoms[1:]):
            logger.warning("Refusing to compile atoms across memory visibility boundaries")
            return None

        # Build raw text from source atoms
        raw_texts = []
        for a in source_atoms:
            text = a.summary or a.content
            raw_texts.append(f"[{a.occurred_at.isoformat()}] {text}")

        combined = "\n".join(raw_texts)

        # Try LLM compilation
        summary = None
        tags = []
        if self._llm_call:
            try:
                prompt = COMPILE_SYSTEM_PROMPT.format(
                    raw_memories=combined,
                    target_layer_name=target_layer.name,
                )
                result = await self._llm_call(
                    "你是一个记忆消化系统。只输出 JSON。", prompt
                )
                if result:
                    import json
                    data = json.loads(result)
                    summary = data.get("summary")
                    tags = data.get("tags", [])
            except Exception as e:
                logger.warning(f"LLM compile failed, using rule-based fallback: {e}")

        # Rule-based fallback: concatenate first sentences
        if not summary:
            sentences = []
            for a in source_atoms:
                text = a.summary or a.content
                first_sent = text.split("。")[0].split("\n")[0][:200]
                sentences.append(first_sent)
            summary = "；".join(sentences[:5])

        # Average emotion
        avg_valence = sum(a.emotion_valence for a in source_atoms) / len(source_atoms)
        avg_arousal = sum(a.emotion_arousal for a in source_atoms) / len(source_atoms)
        avg_dominance = sum(a.emotion_dominance for a in source_atoms) / len(source_atoms)

        # Average confidence weighted by recency
        now = datetime.now(UTC)
        weights = []
        for a in source_atoms:
            hours_old = (now - a.occurred_at).total_seconds() / 3600
            weights.append(max(0.1, 1.0 - hours_old / 168))  # 1 week half-life
        total_w = sum(weights) or 1
        avg_conf = sum(a.confidence * w for a, w in zip(source_atoms, weights)) / total_w

        # Create compiled atom
        import uuid
        compiled_id = f"{target_layer.name.lower()}-{uuid.uuid4().hex[:12]}"
        compiled = MemoryAtom(
            id=compiled_id,
            layer=target_layer,
            content=combined,
            summary=summary,
            occurred_at=datetime.now(UTC),
            confidence=min(1.0, avg_conf),
            salience=min(1.0, avg_conf),
            emotion_valence=avg_valence,
            emotion_arousal=avg_arousal,
            emotion_dominance=avg_dominance,
            source_ids=[a.id for a in source_atoms],
            tags=list(set(tags)),
            scope=source_atoms[0].scope,
            visibility=source_atoms[0].visibility,
            subject_ids=list(source_atoms[0].subject_ids),
            origin={
                key: value
                for key, value in source_atoms[0].origin.items()
                if key not in {"connection_id", "conversation_id"}
            },
            trust_level=min(atom.trust_level for atom in source_atoms),
            retention_policy=(
                "pinned"
                if any(atom.retention_policy == "pinned" for atom in source_atoms)
                else source_atoms[0].retention_policy
            ),
        )
        # Fix relations to use actual compiled id
        compiled.relations = [
            Relation(
                source_id=compiled.id,
                target_id=a.id,
                relation_type=RelationType.DERIVES,
            )
            for a in source_atoms
        ]

        return compiled

    @staticmethod
    def boundary_key(atom: MemoryAtom) -> tuple[object, ...]:
        """Return the privacy partition that may be compiled together."""
        discriminator: object = None
        if atom.scope is MemoryScope.VIEWER:
            discriminator = tuple(sorted(atom.subject_ids))
        elif atom.scope is MemoryScope.STREAM:
            discriminator = atom.origin.get("stream_id")
        elif atom.scope is MemoryScope.CHARACTER:
            discriminator = atom.origin.get("persona_id")
        return atom.scope, atom.visibility, discriminator

    @staticmethod
    def get_eligible_atoms(
        atoms: list[MemoryAtom],
        source_layer: Layer,
        trigger: CompileTrigger,
    ) -> list[MemoryAtom]:
        """Filter atoms that are eligible for compilation.

        Returns atoms that:
        - Are at the source layer
        - Haven't been compiled yet (no outgoing DERIVES relation)
        - Are old enough
        """
        now = datetime.now(UTC)
        eligible = []
        for a in atoms:
            if a.layer != source_layer:
                continue
            if a.is_archived:
                continue
            age_hours = (now - a.occurred_at).total_seconds() / 3600
            if age_hours < trigger.min_age_hours:
                continue
            # Check if already compiled (has DERIVES relation outgoing)
            already_compiled = any(
                r.relation_type == RelationType.DERIVES
                for r in a.relations
            )
            if already_compiled:
                continue
            eligible.append(a)
        return eligible
