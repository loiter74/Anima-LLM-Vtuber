"""应用总配置 - 服务驱动的配置加载"""

import os
import re
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import Field, PrivateAttr, TypeAdapter
from loguru import logger

from .core.base import BaseConfig
from .system import SystemConfig
from .providers.asr import ASRConfig
from .providers.tts import TTSConfig
from .providers.vad import VADConfig
from .agent import AgentConfig
from .persona import PersonaConfig

# 创建 TypeAdapter 用于验证 Discriminated Union 类型
_asr_adapter = TypeAdapter(ASRConfig)
_tts_adapter = TypeAdapter(TTSConfig)
_vad_adapter = TypeAdapter(VADConfig)


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
SERVICES_DIR = CONFIG_DIR / "services"


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


def _load_service_config(service_type: str, service_name: str) -> Dict[str, Any]:
    """
    加载单个服务的配置
    
    Args:
        service_type: 服务类型 (asr/tts/agent)
        service_name: 服务名称 (openai/glm/ollama/mock 等)
    
    Returns:
        Dict: 服务配置
    """
    service_path = SERVICES_DIR / service_type / f"{service_name}.yaml"
    if not service_path.exists():
        raise FileNotFoundError(f"服务配置不存在: {service_path}")
    logger.info(f"加载服务配置: {service_type}/{service_name}")
    return _load_yaml_file(service_path)


class ServicesConfig(BaseConfig):
    """服务组合配置"""
    asr: str = Field(default="mock", description="ASR 服务名称")
    tts: str = Field(default="mock", description="TTS 服务名称")
    agent: str = Field(default="mock", description="Agent 服务名称")
    vad: str = Field(default="mock", description="VAD 服务名称")


class AppConfig(BaseConfig):
    """
    应用总配置
    
    通过 services 字段指定各服务，配置文件位于 config/services/{type}/{name}.yaml
    """
    # 人设
    persona: str = Field(default="default", description="人设名称")
    
    # 服务组合
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    
    # 系统配置
    system: SystemConfig = Field(default_factory=SystemConfig)
    
    # AI 服务配置（从服务配置文件加载）
    asr: Optional[ASRConfig] = Field(default=None)
    tts: Optional[TTSConfig] = Field(default=None)
    agent: Optional[AgentConfig] = Field(default=None)
    vad: Optional[VADConfig] = Field(default=None)
    
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
        1. 读取主配置文件
        2. 从 services/{type}/{name}.yaml 分别加载各服务
        3. 展开环境变量
        4. 应用环境变量覆盖
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        
        main_config = _load_yaml_file(path)
        config = cls._load_services_mode(main_config)
        
        # 展开环境变量
        config._apply_env_expansion()
        
        # 应用环境变量覆盖
        config._apply_env_overrides()
        
        logger.info(f"配置加载完成: persona={config.persona}")
        return config

    @classmethod
    def _load_services_mode(cls, main_config: Dict[str, Any]) -> "AppConfig":
        """Services 模式加载"""
        services_config = main_config.get("services", {})
        
        # 加载各个服务配置
        asr_name = services_config.get("asr", "mock")
        tts_name = services_config.get("tts", "mock")
        agent_name = services_config.get("agent", "mock")
        vad_name = services_config.get("vad", "mock")
        
        asr_data = _load_service_config("asr", asr_name)
        tts_data = _load_service_config("tts", tts_name)
        agent_data = _load_service_config("agent", agent_name)
        vad_data = _load_service_config("vad", vad_name)
        
        # 构建完整配置
        merged = {
            **main_config,
            "asr": asr_data,
            "tts": tts_data,
            "agent": agent_data,
            "vad": vad_data,
        }
        
        return cls(**merged)

    def _apply_env_expansion(self) -> None:
        """递归展开所有配置中的环境变量"""
        # 展开各服务配置中的环境变量
        # 由于 ASRConfig/TTSConfig 是 Discriminated Union，
        # 需要使用 TypeAdapter 来验证
        if self.asr:
            asr_dict = self.asr.model_dump()
            asr_dict = expand_env_vars(asr_dict)
            self.asr = _asr_adapter.validate_python(asr_dict)
        
        if self.tts:
            tts_dict = self.tts.model_dump()
            tts_dict = expand_env_vars(tts_dict)
            self.tts = _tts_adapter.validate_python(tts_dict)
        
        if self.agent:
            agent_dict = self.agent.model_dump()
            agent_dict = expand_env_vars(agent_dict)
            self.agent = AgentConfig.model_validate(agent_dict)

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