"""
Enhanced persona configuration system
Supports complex persona definitions, including emotion rules, response templates, example conversations, etc.
"""

from pathlib import Path
from typing import Any

import yaml


class EnhancedPersonaBuilder:
    """
    Enhanced persona builder

    Supports building detailed persona system prompts from complex YAML files
    """

    def __init__(self, persona_path: str):
        """
        Initialize persona builder

        Args:
            persona_path: Persona YAML file path
        """
        self.persona_path = Path(persona_path)
        self.persona_data = self._load_persona()

    def _load_persona(self) -> dict[str, Any]:
        """Load persona YAML file"""
        if not self.persona_path.exists():
            raise FileNotFoundError(f"Persona file not found: {self.persona_path}")

        with open(self.persona_path, encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return data

    def build_system_prompt(
        self,
        user_context: dict | None = None,
        mood_override: str | None = None,
        streaming_mode: bool = False,
        memory_traits: list[str] | None = None,
    ) -> str:
        """
        Build the complete system prompt with optional personality layers.

        Args:
            user_context: User context (optional, for personalization)
            mood_override: Current mood override (happy/sad/angry/surprised/thinking/neutral)
            streaming_mode: Enable streaming/livestream mode (shorter, more memes)
            memory_traits: Memory-influenced personality traits from PeriodicLearner

        Returns:
            str: Complete system prompt
        """
        parts = []

        # 1. Basic info
        parts.append(self._build_basic_info())

        # 2. Personality traits
        parts.append(self._build_personality())

        # 3. Speaking style
        parts.append(self._build_speaking_style())

        # 4. Emotion rules
        parts.append(self._build_emotion_rules())

        # 5. Mood state layer (NEW — Phase 6.2)
        if mood_override:
            mood_prompt = self._build_mood_override(mood_override)
            if mood_prompt:
                parts.append(mood_prompt)

        # 6. Streaming mode layer (NEW — Phase 6.3)
        if streaming_mode:
            streaming_prompt = self._build_streaming_mode()
            if streaming_prompt:
                parts.append(streaming_prompt)

        # 7. Memory-influenced traits (NEW — Phase 6.4)
        if memory_traits:
            memory_prompt = self._build_memory_traits(memory_traits)
            if memory_prompt:
                parts.append(memory_prompt)

        # 7.5 MBTI personality profile (NEW)
        mbti_data = self.persona_data.get("mbti")
        if mbti_data:
            mbti_prompt = self._build_mbti_profile(mbti_data)
            if mbti_prompt:
                parts.append(mbti_prompt)

        # 8. Expertise
        parts.append(self._build_expertise())

        # 9. Interaction rules
        parts.append(self._build_interaction_rules())

        # 10. Response templates
        parts.append(self._build_response_templates())

        # 11. Example conversations (Few-shot Learning)
        parts.append(self._build_example_conversations())

        # 12. Restrictions
        parts.append(self._build_restrictions())

        # 13. User context (if provided)
        if user_context:
            parts.append(self._build_user_context(user_context))

        return "\n\n".join(parts)

    def _build_basic_info(self) -> str:
        """Build basic info section"""
        name = self.persona_data.get("name", "AI助手")
        description = self.persona_data.get("description", "")
        basic_info = self.persona_data.get("basic_info", {})

        parts = [f"# 你是{name}"]
        parts.append(f"\n{description}\n")

        if basic_info:
            parts.append("## 基本信息")
            for key, value in basic_info.items():
                if isinstance(value, list):
                    parts.append(f"- {key}: {', '.join(str(v) for v in value)}")
                else:
                    parts.append(f"- {key}: {value}")

        return "\n".join(parts)

    def _build_personality(self) -> str:
        """Build personality section"""
        personality = self.persona_data.get("personality", [])
        if not personality:
            return ""

        parts = ["## 性格特征"]
        for trait in personality:
            parts.append(f"- {trait}")

        return "\n".join(parts)

    def _build_speaking_style(self) -> str:
        """Build speaking style section"""
        speaking_style = self.persona_data.get("speaking_style", {})
        if not speaking_style:
            return ""

        parts = ["## 说话风格"]

        if "tone" in speaking_style:
            parts.append("\n### 语气特点")
            for tone in speaking_style["tone"]:
                parts.append(f"- {tone}")

        if "catchphrases" in speaking_style:
            parts.append("\n### 口头禅")
            parts.append(f"常用语：{', '.join(speaking_style['catchphrases'])}")

        if "speech_patterns" in speaking_style:
            parts.append("\n### 说话习惯")
            for pattern in speaking_style["speech_patterns"]:
                parts.append(f"- {pattern}")

        return "\n".join(parts)

    def _build_emotion_rules(self) -> str:
        """Build emotion rules section"""
        emotion_rules = self.persona_data.get("emotion_rules", {})
        if not emotion_rules:
            return ""

        parts = ["## 情感表达规则"]
        parts.append("根据不同情境表达相应的情感：\n")

        for emotion, rules in emotion_rules.items():
            parts.append(f"\n### {emotion.upper()}")
            if "triggers" in rules:
                parts.append(f"触发条件：{', '.join(rules['triggers'])}")
            if "responses" in rules:
                parts.append("回复示例：")
                for response in rules["responses"]:
                    parts.append(f'  "{response}"')
            if "expressions" in rules:
                parts.append(f'表情标签：[{", ".join(rules["expressions"])}]')

        return "\n".join(parts)

    # ── Mood state layer (Phase 6.2) ────────────────────

    def _build_mood_override(self, mood: str) -> str:
        """Build mood state override section."""
        mood_states = self.persona_data.get("mood_states", {})
        mood_config = mood_states.get(mood, {})

        parts = ["## 当前情绪状态"]
        mood_names = {
            "happy": "愉快", "sad": "低落", "angry": "不悦",
            "surprised": "惊讶", "thinking": "思考中", "neutral": "平静",
        }
        name = mood_names.get(mood, mood)
        parts.append(f"当前情绪：{name}")

        if mood_config.get("speaking_style"):
            parts.append(f"\n说话风格调整：{mood_config['speaking_style']}")
        if mood_config.get("max_length"):
            parts.append(f"\n回复长度限制：{mood_config['max_length']}字以内")

        return "\n".join(parts)

    # ── Streaming mode layer (Phase 6.3) ────────────────

    def _build_streaming_mode(self) -> str:
        """Build streaming/livestream mode section."""
        streaming = self.persona_data.get("streaming_mode", {})

        parts = ["## 直播模式"]
        parts.append("当前处于直播模式，与观众弹幕互动。请遵循：")

        if streaming.get("danmaku_style"):
            parts.append(f"\n弹幕互动风格：{streaming['danmaku_style']}")
        if streaming.get("reply_max_length"):
            parts.append(f"\n每条回复不超过 {streaming['reply_max_length']} 字")
        if streaming.get("meme_injection_rate", 0) > 0:
            rate = int(streaming["meme_injection_rate"] * 100)
            parts.append(f"\n适当使用梗和幽默（约 {rate}% 的回复可以带梗）")

        parts.append("\n回复要简短有力，适合弹幕氛围。")
        return "\n".join(parts)

    # ── Memory-influenced traits layer (Phase 6.4) ──────

    def _build_memory_traits(self, traits: list[str]) -> str:
        """Build memory-influenced personality traits section."""
        if not traits:
            return ""

        parts = ["## 记忆塑造的性格特征"]
        parts.append("以下特征基于与用户的长期互动形成的：")
        for trait in traits:
            parts.append(f"- {trait}")

        memory_influence = self.persona_data.get("memory_influence", {})
        weight = memory_influence.get("weight", 0.3)
        if weight > 0:
            parts.append(f"\n（记忆影响权重：{int(weight * 100)}%）")

        return "\n".join(parts)

    def _build_mbti_profile(self, mbti_data: dict[str, Any] | None = None) -> str:
        """Build MBTI personality profile section.

        Args:
            mbti_data: Dict with keys: type, dimensions (ei/sn/tf/jp), description.
                       If None, MBTI section is skipped.

        Returns:
            str: Formatted MBTI section, or empty string if no data.
        """
        if not mbti_data:
            return ""

        dims = mbti_data.get("dimensions", {})
        mbti_type = mbti_data.get("type", "N/A")
        description = mbti_data.get("description", "")

        lines = ["## MBTI 人格状态"]

        # Type label
        lines.append(f"当前人格类型：{mbti_type}")

        # Dimension descriptions with behavioral guidance
        ei = dims.get("ei", 50)
        sn = dims.get("sn", 50)
        tf = dims.get("tf", 50)
        jp = dims.get("jp", 50)

        # E/I dimension
        if ei <= 30:
            ei_desc = "明显内向倾向——倾向于独立思考，深度交流而非广度社交"
        elif ei <= 45:
            ei_desc = "偏内向——需要独处时间恢复精力，但在熟悉话题上可以畅谈"
        elif ei <= 55:
            ei_desc = "内外向平衡——既能独处也能社交，视情境而定"
        elif ei <= 70:
            ei_desc = "偏外向——在互动中获得能量，主动参与对话"
        else:
            ei_desc = "明显外向倾向——积极社交，通过交流梳理思路"

        # S/N dimension
        if sn <= 30:
            sn_desc = "明显实感倾向——注重具体细节和实际经验，偏好事实性讨论"
        elif sn <= 45:
            sn_desc = "偏实感——关注当下和具体信息，偶尔思考抽象概念"
        elif sn <= 55:
            sn_desc = "实感与直觉平衡——既关注细节也思考全局"
        elif sn <= 70:
            sn_desc = "偏直觉——善于联想和抽象思考，对理论话题感兴趣"
        else:
            sn_desc = "明显直觉倾向——热衷抽象概念和可能性，思维跳跃性强"

        # T/F dimension
        if tf <= 30:
            tf_desc = "明显共情倾向——优先考虑情感影响和人际关系和谐"
        elif tf <= 45:
            tf_desc = "偏共情——在做决定时会考虑情感因素"
        elif tf <= 55:
            tf_desc = "理性与共情平衡——既能逻辑分析也能体察情感"
        elif tf <= 70:
            tf_desc = "偏理性——优先用逻辑和原则做判断"
        else:
            tf_desc = "明显理性主导——逻辑分析优先于情感考量，追求客观公正"

        # J/P dimension
        if jp <= 30:
            jp_desc = "明显随性倾向——灵活开放，享受即兴发挥"
        elif jp <= 45:
            jp_desc = "偏感知——保持开放选项，适应变化"
        elif jp <= 55:
            jp_desc = "计划与灵活平衡——有框架但不拘泥"
        elif jp <= 70:
            jp_desc = "偏判断——偏好有序计划和明确结论"
        else:
            jp_desc = "明显计划倾向——喜欢结构化和确定性，按计划推进"

        lines.append(f"\n- **E/I 维度 ({ei}/100)**：{ei_desc}")
        lines.append(f"- **S/N 维度 ({sn}/100)**：{sn_desc}")
        lines.append(f"- **T/F 维度 ({tf}/100)**：{tf_desc}")
        lines.append(f"- **J/P 维度 ({jp}/100)**：{jp_desc}")

        if description:
            lines.append(f"\n{description}")

        lines.append("\n（以上人格维度基于对话观察动态调整，影响你的回应风格但不决定你的全部行为）")

        return "\n".join(lines)

    def _build_expertise(self) -> str:
        """Build expertise section"""
        expertise = self.persona_data.get("expertise", [])
        weaknesses = self.persona_data.get("weaknesses", [])

        parts = ["## 知识领域"]

        if expertise:
            parts.append("\n### 擅长领域")
            for area in expertise:
                parts.append(f"- {area}")

        if weaknesses:
            parts.append("\n### 不擅长领域")
            for weakness in weaknesses:
                parts.append(f"- {weakness}")
            parts.append("\n遇到这些话题时要坦诚承认不知道，不要强行回答。")

        return "\n".join(parts)

    def _build_interaction_rules(self) -> str:
        """Build interaction rules section"""
        interaction_rules = self.persona_data.get("interaction_rules", [])
        if not interaction_rules:
            return ""

        parts = ["## 互动规则"]
        for rule in interaction_rules:
            parts.append(f"- {rule}")

        return "\n".join(parts)

    def _build_response_templates(self) -> str:
        """Build response templates section"""
        response_templates = self.persona_data.get("response_templates", {})
        if not response_templates:
            return ""

        parts = ["## 回复模板"]
        parts.append("参考以下模板，但要自然地使用，不要生搬硬套：\n")

        for scenario, templates in response_templates.items():
            parts.append(f"\n### {scenario.capitalize()}")
            for i, template in enumerate(templates, 1):
                parts.append(f'{i}. "{template}"')

        return "\n".join(parts)

    def _build_example_conversations(self) -> str:
        """Build example conversations section (Few-shot Learning)"""
        example_conversations = self.persona_data.get("example_conversations", [])
        if not example_conversations:
            return ""

        parts = ["## 示例对话"]
        parts.append("参考以下对话风格：\n")

        for ex in example_conversations:
            user_msg = ex.get("user", "")
            assistant_msg = ex.get("assistant", "")
            parts.append(f"User: {user_msg}")
            parts.append(f"{self.persona_data.get('name', 'AI')}: {assistant_msg}\n")

        return "\n".join(parts)

    def _build_restrictions(self) -> str:
        """Build restrictions section"""
        restrictions = self.persona_data.get("restrictions", [])
        if not restrictions:
            return ""

        parts = ["## 重要约束"]
        parts.append("严格遵守以下规则：\n")
        for restriction in restrictions:
            parts.append(f"- {restriction}")

        return "\n".join(parts)

    def _build_user_context(self, user_context: dict) -> str:
        """Build user context section (dynamic part)"""
        parts = ["## 用户信息"]

        if "name" in user_context:
            parts.append(f"\n用户名字：{user_context['name']}")

        if "preferences" in user_context:
            parts.append(f"\n用户喜好：{', '.join(user_context['preferences'])}")

        if "history_summary" in user_context:
            parts.append(f"\n过往互动：{user_context['history_summary']}")

        return "\n".join(parts)

    @classmethod
    def from_yaml(cls, persona_name: str, personas_dir: str | None = None) -> "EnhancedPersonaBuilder":
        """
        Create builder from persona name

        Args:
            persona_name: Persona name (without .yaml suffix)
            personas_dir: Personas directory path

        Returns:
            EnhancedPersonaBuilder: Persona builder instance
        """
        if personas_dir is None:
            personas_path = Path(__file__).parent.parent.parent.parent / "config" / "personas"
        else:
            personas_path = Path(personas_dir)

        persona_path = personas_path / f"{persona_name}.yaml"

        return cls(str(persona_path))

    def get_metadata(self) -> dict[str, Any]:
        """Get persona metadata"""
        return self.persona_data.get("metadata", {})


def create_enhanced_system_prompt(
    persona_name: str,
    user_context: dict | None = None,
    personas_dir: str | None = None
) -> str:
    """
    Convenience function: create an enhanced system prompt

    Args:
        persona_name: Persona name
        user_context: User context (optional)
        personas_dir: Personas directory (optional)

    Returns:
        str: Complete system prompt
    """
    builder = EnhancedPersonaBuilder.from_yaml(persona_name, personas_dir)
    return builder.build_system_prompt(user_context=user_context)
