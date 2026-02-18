"""应用总配置 - profile 驱动的配置加载"""

import os
import re
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import Field, PrivateAttr
from loguru import logger

from .core.base import BaseConfig
from .system import SystemConfig
from .providers.asr import ASRConfig, MockASRConfig
from .providers.tts import TTSConfig, MockTTSConfig
from .agent import AgentConfig
from .persona import PersonaConfig


def expand_env_vars(value):
    """递归展开字符串中的环境变量"""
    if isinstance(value, str):
        pattern = r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)'
        
        def replace_var(match):
            var_name = match.group(1) or match.group(2)
            env_value = os.getenv(var_name, "")
            if not env_value:
                logger.debug(f"环境变量 {var_name} 未设置")
            return env_value
        
        return re.sub(pattern, replace_var, value)
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并字典"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    """加载 YAML 文件"""
    try:
        import yaml
    except ImportError:
        raise ImportError("请安装 PyYAML: pip install pyyaml")
    
    if not path.exists():
        return {}
    
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data or {}


def _load_profile(profile_name: str) -> Dict[str, Any]:
    """加载 profile 配置"""
    profile_path = CONFIG_DIR / "profiles" / f"{profile_name}.yaml"
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile 不存在: {profile_path}")
    logger.info(f"加载 profile: {profile_name}")
    return _load_yaml_file(profile_path)


class AppConfig(BaseConfig):
    """
    应用总配置
    
    AI 服务配置全部从 profile 加载，主配置文件只包含：
    - profile: 服务方案名称
    - persona: 人设名称
    - system: 系统配置
    """
    # 服务方案（必需）
    profile: str = Field(..., description="服务方案名称")
    
    # 人设
    persona: str = Field(default="default", description="人设名称")
    
    # 系统配置
    system: SystemConfig = Field(default_factory=SystemConfig)
    
    # AI 服务配置（从 profile 加载，不设默认值）
    asr: Optional[ASRConfig] = Field(default=None)
    tts: Optional[TTSConfig] = Field(default=None)
    agent: Optional[AgentConfig] = Field(default=None)
    
    # 私有字段
    _persona: Optional[PersonaConfig] = PrivateAttr(default=None)

    def get_persona(self) -> PersonaConfig:
        """获取人设配置（延迟加载）"""
        if self._persona is None:
            self._persona = PersonaConfig.load(self.persona)
        return self._persona

    def get_system_prompt(self) -> str:
        """获取完整的系统提示词"""
        return self.get_persona().build_system_prompt()

    @classmethod
    def from_yaml(cls, path: str) -> "AppConfig":
        """
        从 YAML 文件加载配置
        
        加载流程:
        1. 读取主配置文件（profile, persona, system）
        2. 加载 profile（包含 asr, tts, agent）
        3. 展开环境变量
        4. 应用环境变量覆盖
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        
        main_config = _load_yaml_file(path)
        
        # 获取 profile 名称
        profile_name = main_config.get("profile")
        if not profile_name:
            raise ValueError("配置文件缺少 profile 字段")
        
        # 加载 profile（AI 服务配置）
        profile_data = _load_profile(profile_name)
        
        # 合并：profile 提供基础，main_config 覆盖
        merged = _deep_merge(profile_data, main_config)
        
        # 展开环境变量
        merged = expand_env_vars(merged)
        
        # 创建配置对象
        config = cls(**merged)
        
        # 应用环境变量覆盖
        config._apply_env_overrides()
        
        logger.info(f"配置加载完成: profile={profile_name}, persona={config.persona}")
        return config

    def _apply_env_overrides(self) -> None:
        """应用环境变量覆盖"""
        # LLM 配置
        if self.agent and self.agent.llm_config:
            if os.getenv("LLM_API_KEY"):
                self.agent.llm_config.api_key = os.getenv("LLM_API_KEY")
            if os.getenv("LLM_MODEL") and hasattr(self.agent.llm_config, 'model'):
                self.agent.llm_config.model = os.getenv("LLM_MODEL")
        
        # ASR 配置
        if self.asr and hasattr(self.asr, 'api_key') and os.getenv("ASR_API_KEY"):
            self.asr.api_key = os.getenv("ASR_API_KEY")
        
        # TTS 配置
        if self.tts and hasattr(self.tts, 'api_key') and os.getenv("TTS_API_KEY"):
            self.tts.api_key = os.getenv("TTS_API_KEY")
        
        # 系统配置
        if os.getenv("ANIMA_HOST"):
            self.system.host = os.getenv("ANIMA_HOST")
        if os.getenv("ANIMA_PORT"):
            try:
                self.system.port = int(os.getenv("ANIMA_PORT"))
            except ValueError:
                pass

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "AppConfig":
        """
        智能加载配置
        
        优先级:
        1. 指定的配置文件路径
        2. 环境变量 ANIMA_CONFIG
        3. 默认路径 ./config/config.yaml
        """
        if config_path:
            path = config_path
        elif os.getenv("ANIMA_CONFIG"):
            path = os.getenv("ANIMA_CONFIG")
        else:
            default_paths = [
                Path("config/config.yaml"),
                Path("config.yaml"),
                Path(__file__).parent.parent.parent.parent / "config" / "config.yaml",
            ]
            path = None
            for p in default_paths:
                if p.exists():
                    path = str(p)
                    break
        
        if path and Path(path).exists():
            logger.info(f"从配置文件加载: {path}")
            return cls.from_yaml(path)
        
        raise FileNotFoundError(
            "未找到配置文件。请创建 config/config.yaml 或设置 ANIMA_CONFIG 环境变量"
        )