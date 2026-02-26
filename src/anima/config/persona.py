"""
Persona (人设) 配置模块
支持通过 YAML 文件定义 LLM 角色人设
已合并原 CharacterConfig 的功能
"""

from typing import Optional, List
from pydantic import Field
from .core.base import BaseConfig


class PersonalityTraits(BaseConfig):
    """性格特征"""
    traits: List[str] = Field(
        default_factory=list,
        description="性格特征列表，如：['自信', '毒舌', '可爱']"
    )
    speaking_style: List[str] = Field(
        default_factory=list,
        description="说话风格，如：['短促有力', '中英夹杂']"
    )
    catchphrases: List[str] = Field(
        default_factory=list,
        description="口癖/常用语，如：['Skill issue', 'Cringe']"
    )


class BehaviorRules(BaseConfig):
    """行为准则"""
    forbidden_phrases: List[str] = Field(
        default_factory=lambda: ["作为一个AI语言模型", "我无法", "我不确定"],
        description="禁止使用的短语"
    )
    response_to_praise: Optional[str] = Field(
        default=None,
        description="面对夸奖时的回应模板"
    )
    response_to_criticism: Optional[str] = Field(
        default=None,
        description="面对批评时的回应模板"
    )
    special_behaviors: dict = Field(
        default_factory=dict,
        description="特殊行为规则"
    )


class PersonaConfig(BaseConfig):
    """人设配置（已合并原 CharacterConfig）"""
    # 基本信息
    name: str = Field(default="Anima", description="角色名称")
    avatar: Optional[str] = Field(default=None, description="角色头像 URL")
    role: str = Field(default="AI 助手", description="角色定位")
    
    # 核心人设
    identity: str = Field(
        default="你是一个友好的 AI 助手。",
        description="核心身份描述"
    )
    
    # 性格特征
    personality: PersonalityTraits = Field(
        default_factory=PersonalityTraits,
        description="性格特征配置"
    )
    
    # 行为准则
    behavior: BehaviorRules = Field(
        default_factory=BehaviorRules,
        description="行为准则配置"
    )
    
    # 说话风格
    speaking_style: str = Field(
        default="",
        description="说话风格描述"
    )
    
    # 示例对话
    examples: List[dict] = Field(
        default_factory=list,
        description="对话示例 [{'user': '...', 'ai': '...'}]"
    )
    
    # Emoji 设置
    emoji_style: str = Field(
        default="",
        description="Emoji 使用风格，如：'每条回复包含 1-2 个 Emoji'"
    )
    common_emojis: List[str] = Field(
        default_factory=list,
        description="常用 Emoji 列表"
    )
    
    # 其他设置
    language_mix: bool = Field(
        default=False,
        description="是否中英混合"
    )
    slang_words: List[str] = Field(
        default_factory=list,
        description="网络用语/俚语列表"
    )

    # Live2D 表情提示词（可选）
    live2d_prompt: Optional[str] = Field(
        default=None,
        description="Live2D 表情使用提示词（如果启用）"
    )

    def build_system_prompt(self, live2d_prompt: Optional[str] = None) -> str:
        """
        构建完整的系统提示词

        Args:
            live2d_prompt: Live2D 表情提示词（可选，覆盖配置中的值）

        Returns:
            str: 完整的系统提示词
        """
        parts = []

        # 1. 角色和身份
        parts.append(f"# Role: {self.role}")
        parts.append(f"\n## 核心人设 (Identity)\n{self.identity}")

        # 2. 性格特征
        if self.personality.traits:
            parts.append("\n## 性格特征 (Personality Traits)")
            for i, trait in enumerate(self.personality.traits, 1):
                parts.append(f"{i}. {trait}")

        # 3. 说话风格
        if self.speaking_style:
            parts.append(f"\n## 说话风格 (Speaking Style)\n{self.speaking_style}")

        # 4. 行为准则
        if self.behavior.forbidden_phrases or self.behavior.response_to_praise:
            parts.append("\n## 行为准则 (Behavior Rules)")
            if self.behavior.forbidden_phrases:
                forbidden = "、".join([f'"{p}"' for p in self.behavior.forbidden_phrases])
                parts.append(f"- 禁止说：{forbidden}")
            if self.behavior.response_to_praise:
                parts.append(f"- 面对夸奖：{self.behavior.response_to_praise}")
            if self.behavior.response_to_criticism:
                parts.append(f"- 面对质疑：{self.behavior.response_to_criticism}")

        # 5. Emoji 使用
        if self.emoji_style or self.common_emojis:
            parts.append("\n## Emoji 使用")
            if self.emoji_style:
                parts.append(self.emoji_style)
            if self.common_emojis:
                parts.append(f"常用：{' '.join(self.common_emojis)}")

        # 6. 网络用语
        if self.slang_words:
            parts.append(f"\n## 常用网络用语\n{'、'.join(self.slang_words)}")

        # 7. Live2D 表情提示词（如果提供）
        live2d = live2d_prompt or self.live2d_prompt
        if live2d:
            parts.append(f"\n{live2d}")

        # 8. 对话示例
        if self.examples:
            parts.append("\n## 对话示例 (Examples)")
            for ex in self.examples[:5]:  # 最多 5 个示例
                user = ex.get("user", "")
                ai = ex.get("ai", "")
                if user and ai:
                    parts.append(f"\nUser: {user}\nAI: {ai}")

        return "\n".join(parts)

    @classmethod
    def from_yaml(cls, path: str) -> "PersonaConfig":
        """从 YAML 文件加载人设配置"""
        import yaml
        from pathlib import Path
        
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"人设配置文件不存在: {path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return cls(**data)

    @classmethod
    def load(cls, name: str = "default", personas_dir: str = None) -> "PersonaConfig":
        """
        按名称加载人设
        
        Args:
            name: 人设名称（不含 .yaml 后缀）
            personas_dir: 人设目录路径，默认为 config/personas/
            
        Returns:
            PersonaConfig: 人设配置对象
        """
        from pathlib import Path
        
        if personas_dir is None:
            # 默认路径
            personas_dir = Path(__file__).parent.parent.parent.parent / "config" / "personas"
        else:
            personas_dir = Path(personas_dir)
        
        # 尝试加载
        yaml_path = personas_dir / f"{name}.yaml"
        if yaml_path.exists():
            return cls.from_yaml(str(yaml_path))
        
        # 如果找不到，返回默认
        if name != "default":
            return cls()
        
        raise FileNotFoundError(f"找不到人设配置: {name}")