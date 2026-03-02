"""
增强的人设配置系统
支持复杂的人设定义，包括情感规则、回复模板、示例对话等
"""

from typing import Optional, List, Dict, Any
from pathlib import Path
import yaml


class EnhancedPersonaBuilder:
    """
    增强的人设构建器

    支持从复杂YAML文件构建详细的人设系统提示词
    """

    def __init__(self, persona_path: str):
        """
        初始化人设构建器

        Args:
            persona_path: 人设YAML文件路径
        """
        self.persona_path = Path(persona_path)
        self.persona_data = self._load_persona()

    def _load_persona(self) -> Dict[str, Any]:
        """加载人设YAML文件"""
        if not self.persona_path.exists():
            raise FileNotFoundError(f"人设文件不存在: {self.persona_path}")

        with open(self.persona_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return data

    def build_system_prompt(self, user_context: Optional[Dict] = None) -> str:
        """
        构建完整的系统提示词

        Args:
            user_context: 用户上下文（可选，用于个性化）

        Returns:
            str: 完整的系统提示词
        """
        parts = []

        # 1. 基础信息
        parts.append(self._build_basic_info())

        # 2. 性格特征
        parts.append(self._build_personality())

        # 3. 说话风格
        parts.append(self._build_speaking_style())

        # 4. 情感表达规则
        parts.append(self._build_emotion_rules())

        # 5. 知识领域
        parts.append(self._build_expertise())

        # 6. 互动规则
        parts.append(self._build_interaction_rules())

        # 7. 回复模板
        parts.append(self._build_response_templates())

        # 8. 示例对话（Few-shot Learning）
        parts.append(self._build_example_conversations())

        # 9. 禁忌内容
        parts.append(self._build_restrictions())

        # 10. 用户上下文（如果提供）
        if user_context:
            parts.append(self._build_user_context(user_context))

        return "\n\n".join(parts)

    def _build_basic_info(self) -> str:
        """构建基础信息部分"""
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
        """构建性格特征部分"""
        personality = self.persona_data.get("personality", [])
        if not personality:
            return ""

        parts = ["## 性格特征"]
        for trait in personality:
            parts.append(f"- {trait}")

        return "\n".join(parts)

    def _build_speaking_style(self) -> str:
        """构建说话风格部分"""
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
        """构建情感表达规则"""
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

    def _build_expertise(self) -> str:
        """构建知识领域部分"""
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
        """构建互动规则"""
        interaction_rules = self.persona_data.get("interaction_rules", [])
        if not interaction_rules:
            return ""

        parts = ["## 互动规则"]
        for rule in interaction_rules:
            parts.append(f"- {rule}")

        return "\n".join(parts)

    def _build_response_templates(self) -> str:
        """构建回复模板"""
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
        """构建示例对话（Few-shot Learning）"""
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
        """构建禁忌内容"""
        restrictions = self.persona_data.get("restrictions", [])
        if not restrictions:
            return ""

        parts = ["## 重要约束"]
        parts.append("严格遵守以下规则：\n")
        for restriction in restrictions:
            parts.append(f"- {restriction}")

        return "\n".join(parts)

    def _build_user_context(self, user_context: Dict) -> str:
        """构建用户上下文（动态部分）"""
        parts = ["## 用户信息"]

        if "name" in user_context:
            parts.append(f"\n用户名字：{user_context['name']}")

        if "preferences" in user_context:
            parts.append(f"\n用户喜好：{', '.join(user_context['preferences'])}")

        if "history_summary" in user_context:
            parts.append(f"\n过往互动：{user_context['history_summary']}")

        return "\n".join(parts)

    @classmethod
    def from_yaml(cls, persona_name: str, personas_dir: Optional[str] = None) -> "EnhancedPersonaBuilder":
        """
        从人设名称创建构建器

        Args:
            persona_name: 人设名称（不含.yaml后缀）
            personas_dir: 人设目录路径

        Returns:
            EnhancedPersonaBuilder: 人设构建器实例
        """
        if personas_dir is None:
            personas_dir = Path(__file__).parent.parent.parent.parent / "config" / "personas"
        else:
            personas_dir = Path(personas_dir)

        persona_path = personas_dir / f"{persona_name}.yaml"

        return cls(str(persona_path))

    def get_metadata(self) -> Dict[str, Any]:
        """获取人设元数据"""
        return self.persona_data.get("metadata", {})


def create_enhanced_system_prompt(
    persona_name: str,
    user_context: Optional[Dict] = None,
    personas_dir: Optional[str] = None
) -> str:
    """
    快捷函数：创建增强的系统提示词

    Args:
        persona_name: 人设名称
        user_context: 用户上下文（可选）
        personas_dir: 人设目录（可选）

    Returns:
        str: 完整的系统提示词
    """
    builder = EnhancedPersonaBuilder.from_yaml(persona_name, personas_dir)
    return builder.build_system_prompt(user_context=user_context)
