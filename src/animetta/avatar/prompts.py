"""
Emotion Prompt Builder
Generates expression usage guidelines for the LLM
"""

from pathlib import Path

from animetta.avatar.performance import PERFORMANCE_BASES, PERFORMANCE_INTENSITIES


class EmotionPromptBuilder:
    """
    Emotion Prompt Builder

    Generates system prompts with expression usage guidelines to help the LLM correctly use emotion tags
    """

    # Default emotion definitions
    DEFAULT_EMOTIONS: dict[str, str] = {
        "happy": "开心、快乐、愉快",
        "sad": "难过、悲伤、失落",
        "angry": "生气、愤怒、恼火",
        "surprised": "惊讶、震惊、意外",
        "neutral": "中性、平静",
        "thinking": "思考、沉思",
    }

    def __init__(self, emotions: dict[str, str] | None = None, language: str = "zh"):
        """
        Initialize the prompt builder

        Args:
            emotions: Emotion dictionary {emotion_name: description}
            language: Language ("zh" or "en")
        """
        self.emotions = emotions or self.DEFAULT_EMOTIONS
        self.language = language

    def build_prompt(self) -> str:
        """
        Build the expression usage guideline prompt

        Returns:
            Formatted prompt text
        """
        if self.language == "zh":
            return self._build_zh_prompt()
        else:
            return self._build_en_prompt()

    def _build_zh_prompt(self) -> str:
        """Build Chinese prompt"""
        lines = [
            "# Live2D 表情使用指南",
            "",
            "你可以在回复中使用以下表情标签来表达情感：",
            "",
            "## 可用表情",
        ]

        # 添加表情列表
        for emotion, description in self.emotions.items():
            lines.append(f"- [{emotion}] - {description}")

        lines.extend(
            [
                "",
                "## 使用方法",
                "在文本中使用表情标签，标签会自动从语音中移除，不影响 TTS 发音。",
                "",
                "## 示例",
            ]
        )

        # 添加示例
        examples = self._get_examples()
        for example in examples:
            lines.append(f'"{example}"')

        lines.extend(
            [
                "",
                "## 【重要】强制要求",
                "**每条回复必须至少包含 1-2 个表情标签！**",
                "表情标签会自动从语音中移除，不影响 TTS 发音。",
                "",
                "## 使用技巧",
                "1. 根据语境选择合适的表情",
                "2. 一个回复中可以使用多个表情标签",
                "3. 表情标签放在对应情感词语之后效果更好",
            ]
        )

        return "\n".join(lines)

    def _build_en_prompt(self) -> str:
        """Build English prompt"""
        lines = [
            "# Live2D Expression Guide",
            "",
            "You can use the following expression tags to convey emotions in your responses:",
            "",
            "## Available Expressions",
        ]

        for emotion, description in self.emotions.items():
            lines.append(f"- [{emotion}] - {description}")

        lines.extend(
            [
                "",
                "## Usage",
                "Use expression tags in your text. They will be automatically removed from speech synthesis.",
                "",
                "## Examples",
            ]
        )

        examples = self._get_examples_en()
        for example in examples:
            lines.append(f'"{example}"')

        lines.extend(
            [
                "",
                "## Notes",
                "1. Don't overuse expression tags, keep it natural",
                "2. Choose appropriate expressions based on context",
                "3. You can use multiple expression tags in one response",
                "4. Expression tags are automatically removed from TTS input",
            ]
        )

        return "\n".join(lines)

    def _get_examples(self) -> list[str]:
        """Get Chinese examples"""
        examples = []

        if "happy" in self.emotions:
            examples.append("你好！[happy] 很高兴见到你！")

        if "thinking" in self.emotions:
            examples.append("让我想想...[thinking] 这个问题很有意思。")

        if "surprised" in self.emotions:
            examples.append("哇！[surprised] 这是真的吗？")

        if "sad" in self.emotions:
            examples.append("有点难过...[sad] 希望下次能更好。")

        if "angry" in self.emotions:
            examples.append("这太不公平了！[angry] 我不能接受。")

        return examples

    def _get_examples_en(self) -> list[str]:
        """Get English examples"""
        examples = []

        if "happy" in self.emotions:
            examples.append("Hello! [happy] Nice to meet you!")

        if "thinking" in self.emotions:
            examples.append("Let me think... [thinking] This is interesting.")

        if "surprised" in self.emotions:
            examples.append("Wow! [surprised] Is that true?")

        if "sad" in self.emotions:
            examples.append("I'm a bit sad... [sad] Hope it goes better next time.")

        if "angry" in self.emotions:
            examples.append("This is unfair! [angry] I can't accept this.")

        return examples

    @classmethod
    def from_config(cls, config: dict) -> "EmotionPromptBuilder":
        """
        Create a builder from configuration

        Args:
            config: Configuration dict containing valid_emotions list

        Returns:
            EmotionPromptBuilder instance
        """
        valid_emotions = config.get("valid_emotions", [])
        emotions = {}

        # Use default descriptions
        for emotion in valid_emotions:
            if emotion in cls.DEFAULT_EMOTIONS:
                emotions[emotion] = cls.DEFAULT_EMOTIONS[emotion]
            else:
                emotions[emotion] = emotion  # Use name as description

        return cls(emotions=emotions)


class PerformancePromptBuilder:
    """Build the bounded, calm-first Live2D performance contract."""

    def __init__(self, language: str = "zh"):
        self.language = language

    def build_prompt(self) -> str:
        """Return a provider-neutral in-band marker contract."""

        bases = " | ".join(PERFORMANCE_BASES)
        intensities = " | ".join(PERFORMANCE_INTENSITIES)
        if self.language == "en":
            return "\n".join(
                [
                    "# Live2D Semantic Performance",
                    "",
                    "Start every response with exactly one marker:",
                    "`[live2d:<base>|<intensity>|<accent>]`",
                    "",
                    f"- base: {bases}",
                    f"- intensity: {intensities}",
                    "- accent: none",
                    "",
                    "Use `[live2d:calm|subtle|none]` for most responses.",
                    "Choose another value only when the spoken content clearly expresses it.",
                    "Never output a raw parameter, motion group, motion index, or more than one marker.",
                ]
            )

        return "\n".join(
            [
                "# Live2D 语义表演指南",
                "",
                "每条回复必须在回复最开头输出以下 marker，且只能输出一个：",
                "`[live2d:<base>|<intensity>|<accent>]`",
                "",
                f"- base: {bases}",
                f"- intensity: {intensities}",
                "- accent: none",
                "",
                "大多数回复使用 calm，即 `[live2d:calm|subtle|none]`。",
                "只有回复正文明确表达对应情绪时才选择其他值。",
                "禁止输出原始模型参数、动作组、动作编号或多个 marker。",
            ]
        )


def load_prompt_template(template_path: str) -> str:
    """
    Load a prompt template from a file

    Args:
        template_path: Template file path

    Returns:
        Template content
    """
    path = Path(template_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    else:
        raise FileNotFoundError(f"Prompt template not found: {template_path}")
