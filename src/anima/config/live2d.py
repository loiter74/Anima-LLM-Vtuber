"""
Live2D 配置类
定义 Live2D 模型的配置和表情映射
"""

from typing import Dict, List, Optional
from pydantic import Field, BaseModel
from pathlib import Path

from .core.base import BaseConfig


class Live2DModelConfig(BaseModel):
    """Live2D 模型配置"""
    path: str = Field(default="/live2d/haru/haru_greeter_t03.model3.json", description="模型文件路径")
    scale: float = Field(default=0.5, description="模型缩放比例")
    position: Dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0}, description="模型位置 (x, y)")


class Live2DLipSyncConfig(BaseModel):
    """Live2D 口型同步配置"""
    enabled: bool = Field(default=True, description="是否启用口型同步")
    sensitivity: float = Field(default=1.0, ge=0.0, le=2.0, description="嘴部动作灵敏度")
    smoothing: float = Field(default=0.5, ge=0.0, le=1.0, description="平滑系数")


class Live2DConfig(BaseConfig):
    """
    Live2D 配置

    基于情感内容的 Live2D 表情控制
    """
    # 是否启用 Live2D
    enabled: bool = Field(default=True, description="是否启用 Live2D")

    # 模型配置
    model: Live2DModelConfig = Field(default_factory=Live2DModelConfig, description="Live2D 模型配置")

    # 表情映射：emotion name → Live2D motion index
    # 例如: {"happy": 3, "sad": 1, "angry": 2}
    emotion_map: Dict[str, int] = Field(
        default_factory=lambda: {
            "happy": 3,
            "sad": 1,
            "angry": 2,
            "surprised": 4,
            "neutral": 0,
            "thinking": 5,
        },
        description="表情名称到 Live2D 动作索引的映射"
    )

    # 有效表情列表（用于提示词）
    valid_emotions: List[str] = Field(
        default_factory=lambda: ["happy", "sad", "angry", "surprised", "neutral", "thinking"],
        description="有效的表情列表"
    )

    # 口型同步配置
    lip_sync: Live2DLipSyncConfig = Field(default_factory=Live2DLipSyncConfig, description="口型同步配置")

    # 提示词模板路径
    prompt_template_path: str = Field(
        default="config/prompts/live2d_expression.txt",
        description="表情使用指导提示词模板路径"
    )

    @classmethod
    def from_yaml(cls, path: str) -> "Live2DConfig":
        """
        从 YAML 文件加载配置

        Args:
            path: 配置文件路径

        Returns:
            Live2DConfig 实例
        """
        import yaml
        path = Path(path)
        if not path.exists():
            logger.warning(f"Live2D 配置文件不存在: {path}，使用默认配置")
            return cls()

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def get_emotion_names(self) -> List[str]:
        """获取所有表情名称列表"""
        return list(self.emotion_map.keys())

    def get_motion_index(self, emotion: str) -> Optional[int]:
        """
        获取表情对应的 Live2D 动作索引

        Args:
            emotion: 表情名称

        Returns:
            动作索引，如果不存在则返回 None
        """
        return self.emotion_map.get(emotion)

    def is_valid_emotion(self, emotion: str) -> bool:
        """
        检查表情是否有效

        Args:
            emotion: 表情名称

        Returns:
            是否有效
        """
        return emotion in self.emotion_map


# 全局 Live2D 配置实例（延迟加载）
_live2d_config: Optional[Live2DConfig] = None


def get_live2d_config() -> Live2DConfig:
    """
    获取全局 Live2D 配置（单例）

    Returns:
        Live2DConfig 实例
    """
    global _live2d_config
    if _live2d_config is None:
        config_path = Path("config/features/live2d.yaml")
        if config_path.exists():
            _live2d_config = Live2DConfig.from_yaml(str(config_path))
        else:
            _live2d_config = Live2DConfig()
    return _live2d_config


def reset_live2d_config():
    """重置全局 Live2D 配置（用于测试）"""
    global _live2d_config
    _live2d_config = None


# 导入 logger
from loguru import logger
