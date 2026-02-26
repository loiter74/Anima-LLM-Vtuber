"""
表情提示词构建器
为 LLM 生成表情使用指导
"""

from typing import List, Optional, Dict
from pathlib import Path


class EmotionPromptBuilder:
    """
    表情提示词构建器

    生成包含表情使用指导的系统提示，帮助 LLM 正确使用表情标签
    """

    # 默认表情定义
    DEFAULT_EMOTIONS: Dict[str, str] = {
        "happy": "开心、快乐、愉快",
        "sad": "难过、悲伤、失落",
        "angry": "生气、愤怒、恼火",
        "surprised": "惊讶、震惊、意外",
        "neutral": "中性、平静",
        "thinking": "思考、沉思",
    }

    def __init__(
        self,
        emotions: Optional[Dict[str, str]] = None,
        language: str = "zh"
    ):
        """
        初始化提示词构建器

        Args:
            emotions: 表情字典 {emotion_name: description}
            language: 语言 ("zh" 或 "en")
        """
        self.emotions = emotions or self.DEFAULT_EMOTIONS
        self.language = language

    def build_prompt(self) -> str:
        """
        构建表情使用指导提示词

        Returns:
            格式化的提示词文本
        """
        if self.language == "zh":
            return self._build_zh_prompt()
        else:
            return self._build_en_prompt()

    def _build_zh_prompt(self) -> str:
        """构建中文提示词"""
        lines = [
            "# Live2D 表情使用指南",
            "",
            "你可以在回复中使用以下表情标签来表达情感：",
            "",
            "## 可用表情"
        ]

        # 添加表情列表
        for emotion, description in self.emotions.items():
            lines.append(f"- [{emotion}] - {description}")

        lines.extend([
            "",
            "## 使用方法",
            "在文本中使用表情标签，标签会自动从语音中移除，不影响 TTS 发音。",
            "",
            "## 示例"
        ])

        # 添加示例
        examples = self._get_examples()
        for example in examples:
            lines.append(f'"{example}"')

        lines.extend([
            "",
            "## 注意",
            "1. 不要过度使用表情标签，保持自然",
            "2. 根据语境选择合适的表情",
            "3. 一个回复中可以使用多个表情标签",
            "4. 表情标签会自动从 TTS 输入中移除"
        ])

        return "\n".join(lines)

    def _build_en_prompt(self) -> str:
        """构建英文提示词"""
        lines = [
            "# Live2D Expression Guide",
            "",
            "You can use the following expression tags to convey emotions in your responses:",
            "",
            "## Available Expressions"
        ]

        for emotion, description in self.emotions.items():
            lines.append(f"- [{emotion}] - {description}")

        lines.extend([
            "",
            "## Usage",
            "Use expression tags in your text. They will be automatically removed from speech synthesis.",
            "",
            "## Examples"
        ])

        examples = self._get_examples_en()
        for example in examples:
            lines.append(f'"{example}"')

        lines.extend([
            "",
            "## Notes",
            "1. Don't overuse expression tags, keep it natural",
            "2. Choose appropriate expressions based on context",
            "3. You can use multiple expression tags in one response",
            "4. Expression tags are automatically removed from TTS input"
        ])

        return "\n".join(lines)

    def _get_examples(self) -> List[str]:
        """获取中文示例"""
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

    def _get_examples_en(self) -> List[str]:
        """获取英文示例"""
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
        从配置创建构建器

        Args:
            config: 配置字典，包含 valid_emotions 列表

        Returns:
            EmotionPromptBuilder 实例
        """
        valid_emotions = config.get("valid_emotions", [])
        emotions = {}

        # 使用默认描述
        for emotion in valid_emotions:
            if emotion in cls.DEFAULT_EMOTIONS:
                emotions[emotion] = cls.DEFAULT_EMOTIONS[emotion]
            else:
                emotions[emotion] = emotion  # 使用名称作为描述

        return cls(emotions=emotions)


def load_prompt_template(template_path: str) -> str:
    """
    从文件加载提示词模板

    Args:
        template_path: 模板文件路径

    Returns:
        模板内容
    """
    path = Path(template_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    else:
        raise FileNotFoundError(f"提示词模板不存在: {template_path}")
