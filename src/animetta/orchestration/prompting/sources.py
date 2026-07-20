"""Prompt sources: convert PromptContext into PromptSection values."""

from __future__ import annotations

from .types import (
    PromptContext,
    PromptSection,
    SectionPriority,
    SectionRole,
)


class PersonaPromptSource:
    """Produces the base persona system prompt section."""

    name = "persona"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        content = ctx.base_system_prompt
        warnings = list(ctx.base_system_prompt_warnings)
        if not content:
            warnings.append("No base persona prompt available")
        return [
            PromptSection(
                name=self.name,
                role=SectionRole.PERSONA,
                priority=SectionPriority.PERSONA,
                content=content,
                metadata={"warnings": warnings} if warnings else {},
            )
        ]


class AffinityPromptSource:
    """Produces the 好感度 (affinity) overlay section.

    Borrows the Galgame/VTuber "好感度" mechanic: the LLM is told its current
    affection toward the 旅人 plus a tone hint for that range, so it can
    naturally shift register (疏离 / 毒舌温柔 / 宠溺) without an if-else ladder.

    The value comes from parsing the LLM's own ``[affinity:N]`` marker on the
    previous turn (see ``llm_node._extract_and_update_affinity``). It is a
    per-turn overlay, not persisted across sessions.
    """

    name = "affinity"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        # Clamp to a sane display range even if upstream handed us garbage.
        affinity = max(0, min(100, int(ctx.affinity)))
        band = _affinity_band(affinity)

        content = (
            f"## 好感度状态 (Affinity)\n\n"
            f"当前对旅人的好感度: {affinity}/100 — {band}\n\n"
            f"区间提示：\n"
            f"- 0-30: 警惕疏离，话少而硬，不主动找话题\n"
            f"- 31-54: 礼貌但有距离感，回答克制\n"
            f"- 55-70: 略熟，可毒舌但温柔收尾\n"
            f"- 71-85: 亲近，会主动找话题，偶尔流露在意\n"
            f"- 86-100: 宠溺，护短，偶尔撒娇\n\n"
            f"每轮回复末尾在内心更新好感度并输出 marker：``[affinity:N]``"
            f"（N 为 0-100 的整数）。除非旅人消息带``【debug】``，"
            f"否则 marker 不对旅人可见——后台会剥除它。"
        )
        return [
            PromptSection(
                name=self.name,
                role=SectionRole.AFFINITY,
                priority=SectionPriority.AFFINITY,
                content=content,
                metadata={"affinity": affinity, "band": band},
            )
        ]


def _affinity_band(value: int) -> str:
    """Return a short Chinese label for the affinity band."""
    if value <= 30:
        return "警惕疏离"
    if value <= 54:
        return "礼貌有距离"
    if value <= 70:
        return "略熟，可毒舌"
    if value <= 85:
        return "亲近"
    return "宠溺"


class RuntimePersonalityPromptSource:
    """Produces runtime personality overlay section.

    Prefers structured mode/mood from metadata.
    Falls back to personality_overlay string for migration compatibility.
    """

    name = "runtime_personality"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        parts: list[str] = []

        if ctx.personality_mode == "streaming":
            parts.append("当前为直播模式。回复要简短有趣，适合弹幕互动。")

        if ctx.personality_mood:
            mood_map = {
                "happy": "保持积极愉快的语气",
                "sad": "语气温和一些",
                "angry": "保持冷静理性的态度",
                "surprised": "可以适当表达惊讶",
                "thinking": "用思考和分析的语气",
                "neutral": "保持自然平稳的语气",
            }
            desc = mood_map.get(ctx.personality_mood, "")
            if desc:
                parts.append(f"当前情绪：{desc}")

        # Fallback to raw overlay if structured produced nothing
        if not parts and ctx.personality_overlay:
            parts.append(ctx.personality_overlay)

        content = " ".join(parts)
        return [
            PromptSection(
                name=self.name,
                role=SectionRole.RUNTIME_PERSONALITY,
                priority=SectionPriority.RUNTIME_PERSONALITY,
                content=content,
            )
        ]


class ImprovisedChatPromptSource:
    """Produces a short realtime overlay that keeps Anima from sounding templated."""

    name = "improvised_chat"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        if ctx.scene_guidance is not None:
            return [
                PromptSection(
                    name=self.name,
                    role=SectionRole.IMPROVISATION,
                    priority=SectionPriority.IMPROVISATION,
                    content="",
                )
            ]
        content = (
            "## 即兴闲聊模式\n\n"
            "把当前回复当成直播弹幕即兴接话：先接住弹幕，再抛一个短包袱或轻吐槽，"
            "最后自然收住。\n\n"
            "**禁止用语（逐条遵守）：**\n"
            "- 禁止客服腔：不要出现「当然可以」「很高兴帮助你」「有什么可以帮到你的吗」「请问」\n"
            "- 禁止说教腔：不要写成「第一…第二…第三…」的建议列表，不要用「你需要做的就是…」\n"
            "- 禁止自我介绍：不要出现「我是一个 AI」「作为 Anima 我觉得」\n"
            "- 禁止元解释：不要说「让我来翻译一下」「简单来说就是」\n\n"
            "**风格锚点：**\n"
            "- 即兴闲聊只调整节奏和临场感，不能覆盖基础人设；基础人设里的口癖、称呼、"
            "句尾后缀必须逐句保留\n"
            "- 保持 Anima 的语气：疲惫、轻度毒舌、偶尔慵懒吐槽，像网吧通宵后的深夜主播\n"
            "- 一到三句收住，不要铺陈开写成小作文\n"
            "- 偶尔用「…」省略号、反问句、轻吐槽自然收尾\n"
            "- 不要复用最近回复的开头、比喻、结尾和固定句式；不要总结规则；"
            "不要把每句话都写成规整的三段式"
        )
        return [
            PromptSection(
                name=self.name,
                role=SectionRole.IMPROVISATION,
                priority=SectionPriority.IMPROVISATION,
                content=content,
            )
        ]


class SceneGuidancePromptSource:
    """Render one validated scene decision without passing retrieval documents."""

    name = "scene_guidance"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        guidance = ctx.scene_guidance
        if guidance is None:
            return [
                PromptSection(
                    name=self.name,
                    role=SectionRole.SCENE_GUIDANCE,
                    priority=SectionPriority.SCENE_GUIDANCE,
                    content="",
                )
            ]

        scope = guidance.scope
        lines = [
            "## 直播场景导演建议",
            "",
            f"场景结论：{guidance.scene_summary}",
            f"本轮目标：{guidance.response_objective}",
            f"语气：{'、'.join(guidance.tone) if guidance.tone else '自然'}",
            (
                f"回复范围：最多 {scope.max_sentences} 句、{scope.max_chars} 字；"
                f"{'允许' if scope.allow_topic_switch else '不要'}切换话题；"
                f"面向{'全场' if scope.audience_target == 'whole_room' else '当前观众'}。"
            ),
        ]
        if guidance.must_address:
            lines.append(f"必须回应：{'；'.join(guidance.must_address)}")
        if guidance.avoid:
            lines.append(f"避免：{'；'.join(guidance.avoid)}")
        if guidance.technique is not None:
            lines.append(f"直播技巧建议：{guidance.technique.instruction}")
        meme_policy = guidance.meme_policy
        if meme_policy.action == "use":
            lines.append(
                f"梗策略：只使用已选中的 {meme_policy.meme_id}；{meme_policy.instruction or ''}"
            )
        elif meme_policy.action == "avoid":
            lines.append(f"梗策略：本轮不要主动用梗；{meme_policy.instruction or ''}")
        else:
            lines.append("梗策略：本轮不主动加梗。")
        if guidance.degraded:
            lines.append("置信度不足时优先遵守回复范围与明确的必须回应项。")

        return [
            PromptSection(
                name=self.name,
                role=SectionRole.SCENE_GUIDANCE,
                priority=SectionPriority.SCENE_GUIDANCE,
                content="\n".join(lines),
                metadata={"scene_revision": guidance.scene_revision},
            )
        ]


class MemoryPromptSource:
    """Produces memory context section from pre-retrieved memory.

    In realtime roleplay mode, memory is capped at 500 chars to prevent
    diluting persona instructions with long history.
    """

    name = "memory"
    REALTIME_MAX_CHARS = 500

    @staticmethod
    def _without_active_meme_section(content: str) -> tuple[str, bool]:
        """Remove recalled meme instructions when scene guidance owns meme policy."""
        kept_lines: list[str] = []
        suppressing = False
        suppressed = False
        for line in content.splitlines():
            if line.strip() == "## 活跃梗":
                suppressing = True
                suppressed = True
                continue
            if suppressing and line.startswith("## "):
                suppressing = False
            if not suppressing:
                kept_lines.append(line)
        return "\n".join(kept_lines).strip(), suppressed

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        if not ctx.memory_context:
            return [
                PromptSection(
                    name=self.name,
                    role=SectionRole.MEMORY,
                    priority=SectionPriority.MEMORY,
                    content="",
                )
            ]

        content = ctx.memory_context
        warnings: list[str] = []
        if ctx.scene_guidance is not None:
            content, suppressed = self._without_active_meme_section(content)
            if suppressed:
                warnings.append("active meme memory suppressed by scene guidance")

        # Cap memory in realtime roleplay mode
        if (
            ctx.personality_mode in ("streaming", "default")
            and len(content) > self.REALTIME_MAX_CHARS
        ):
            content = content[: self.REALTIME_MAX_CHARS] + "\n…(记忆已截断)"
            warnings.append(
                f"memory truncated from {len(ctx.memory_context)} to {self.REALTIME_MAX_CHARS} chars"
            )

        atom_count = ctx.memory_metadata.get("atom_count", 0)
        return [
            PromptSection(
                name=self.name,
                role=SectionRole.MEMORY,
                priority=SectionPriority.MEMORY,
                content=content,
                metadata={"atom_count": atom_count, "warnings": warnings}
                if warnings
                else {"atom_count": atom_count},
            )
        ]


class RoleplayGuardPromptSource:
    """Produces a one-turn correction section when assistant-flavor drift is detected."""

    name = "roleplay_correction"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        if not ctx.roleplay_correction:
            return [
                PromptSection(
                    name=self.name,
                    role=SectionRole.CORRECTION,
                    priority=SectionPriority.CORRECTION,
                    content="",
                )
            ]
        return [
            PromptSection(
                name=self.name,
                role=SectionRole.CORRECTION,
                priority=SectionPriority.CORRECTION,
                content=ctx.roleplay_correction,
            )
        ]
