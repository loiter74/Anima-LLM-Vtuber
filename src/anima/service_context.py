"""
服务上下文 - 核心服务容器
管理所有服务实例（ASR, TTS, LLM）的初始化、存储和生命周期
"""

from typing import Callable, Optional
from loguru import logger

from .config import AppConfig, ASRConfig, TTSConfig, AgentConfig, PersonaConfig, VADConfig
from .services import ASRInterface, TTSInterface, LLMInterface
from .services.asr import ASRFactory
from .services.tts import TTSFactory
from .services.llm import LLMFactory
from .services.vad import VADInterface, VADFactory
from .memory import MemorySystem


class ServiceContext:
    """
    服务上下文类

    负责：
    1. 存储和管理所有服务实例（ASR, TTS, LLM）
    2. 根据配置初始化服务（通过工厂模式）
    3. 管理会话状态
    4. 处理配置热切换

    每个客户端连接对应一个独立的 ServiceContext 实例
    """

    def __init__(self):
        # 配置
        self.config: Optional[AppConfig] = None

        # 服务实例
        self.asr_engine: Optional[ASRInterface] = None
        self.tts_engine: Optional[TTSInterface] = None
        self.llm_engine: Optional[LLMInterface] = None  # 底座LLM（GLM API，应用persona）
        self.local_llm_engine: Optional[LLMInterface] = None  # 本地LLM（简单应答，无persona）
        self.vad_engine: Optional[VADInterface] = None

        # 记忆系统
        self.memory_system: Optional[MemorySystem] = None

        # 会话状态
        self.session_id: Optional[str] = None
        self.is_speaking: bool = False
        self.is_processing: bool = False

        # 回调函数 - 用于向客户端发送消息
        self.send_text: Optional[Callable] = None

    def __str__(self) -> str:
        return (
            f"ServiceContext(\n"
            f"  session_id={self.session_id},\n"
            f"  asr={type(self.asr_engine).__name__ if self.asr_engine else 'Not Loaded'},\n"
            f"  tts={type(self.tts_engine).__name__ if self.tts_engine else 'Not Loaded'},\n"
            f"  llm={type(self.llm_engine).__name__ if self.llm_engine else 'Not Loaded'},\n"
            f"  is_speaking={self.is_speaking},\n"
            f"  is_processing={self.is_processing}\n"
            f")"
        )

    # ========================================
    # 初始化方法
    # ========================================

    async def load_from_config(self, config: AppConfig) -> None:
        """
        从配置加载所有服务

        Args:
            config: 应用配置对象
        """
        self.config = config
        logger.info(f"[{self.session_id}] 正在从配置加载服务...")

        # 初始化各个服务
        await self.init_asr(config.asr)
        await self.init_tts(config.tts)
        await self.init_llm(config.agent, config.get_persona(), app_config=config)
        await self.init_local_llm(config.local_llm, app_config=config)
        await self.init_vad(config.vad)
        await self.init_memory()

        logger.info(f"[{self.session_id}] 服务加载完成")

    async def load_cache(
        self,
        config: AppConfig,
        asr_engine: Optional[ASRInterface] = None,
        tts_engine: Optional[TTSInterface] = None,
        llm_engine: Optional[LLMInterface] = None,
        send_text: Optional[Callable] = None,
    ) -> None:
        """
        从缓存加载服务（复用已有实例）
        用于共享服务的场景，避免重复初始化

        Args:
            config: 应用配置
            asr_engine: 已有的 ASR 实例（可选）
            tts_engine: 已有的 TTS 实例（可选）
            llm_engine: 已有的 LLM 实例（可选）
            send_text: 发送消息的回调函数
        """
        self.config = config
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        self.llm_engine = llm_engine
        self.send_text = send_text

        logger.debug(f"[{self.session_id}] 从缓存加载服务上下文")

    async def init_asr(self, asr_config: ASRConfig) -> None:
        """
        初始化 ASR 服务（使用工厂模式）

        Args:
            asr_config: ASR 配置
        """
        if self.asr_engine is not None:
            logger.debug(f"[{self.session_id}] ASR 已初始化，跳过")
            return

        provider = asr_config.type
        model = getattr(asr_config, 'model', 'default')
        logger.info(f"[{self.session_id}] 初始化 ASR: {provider}/{model}")

        self.asr_engine = ASRFactory.create(
            provider=provider,
            api_key=getattr(asr_config, 'api_key', None),
            model=getattr(asr_config, 'model', 'whisper-1'),
            language=asr_config.language,
            base_url=getattr(asr_config, 'base_url', None),
            stream=getattr(asr_config, 'stream', False),
            # faster-whisper 特定参数
            device=getattr(asr_config, 'device', 'auto'),
            compute_type=getattr(asr_config, 'compute_type', 'default'),
            download_root=getattr(asr_config, 'download_root', None),
            beam_size=getattr(asr_config, 'beam_size', 5),
            vad_filter=getattr(asr_config, 'vad_filter', True),
            vad_parameters=getattr(asr_config, 'vad_parameters', {})
        )

    async def init_tts(self, tts_config: TTSConfig) -> None:
        """
        初始化 TTS 服务（使用工厂模式）

        Args:
            tts_config: TTS 配置
        """
        if self.tts_engine is not None:
            logger.debug(f"[{self.session_id}] TTS 已初始化，跳过")
            return

        provider = tts_config.type
        model = getattr(tts_config, 'model', 'default')
        logger.info(f"[{self.session_id}] 初始化 TTS: {provider}/{model}")

        self.tts_engine = TTSFactory.create(
            provider=provider,
            api_key=getattr(tts_config, 'api_key', None),
            model=getattr(tts_config, 'model', 'tts-1'),
            voice=getattr(tts_config, 'voice', 'alloy'),
            base_url=getattr(tts_config, 'base_url', None),
            response_format=getattr(tts_config, 'response_format', 'wav'),
            speed=getattr(tts_config, 'speed', 1.0),
            volume=getattr(tts_config, 'volume', 1.0)
        )

    async def init_llm(self, agent_config: AgentConfig, persona_config: PersonaConfig, app_config: AppConfig = None) -> None:
        """
        初始化 LLM 服务（使用工厂模式 + 配置对象多态）

        Args:
            agent_config: Agent 配置（包含 LLM 配置）
            character_config: 角色配置
            app_config: 应用配置（用于获取人设）
        """
        if self.llm_engine is not None:
            logger.debug(f"[{self.session_id}] LLM 已初始化，跳过")
            return

        llm_config = agent_config.llm_config
        logger.info(f"[{self.session_id}] 初始化 LLM: {llm_config.type}/{llm_config.model}")
        logger.debug(f"[{self.session_id}] LLM Config 类: {type(llm_config).__name__}")

        # 构建系统提示词（优先使用人设系统）
        if app_config:
            # 获取 Live2D 表情提示词（如果启用）
            live2d_prompt = self._get_live2d_prompt()
            system_prompt = app_config.get_system_prompt(live2d_prompt=live2d_prompt)
            persona_name = app_config.persona
            logger.info(f"[{self.session_id}] 使用人设: {persona_name}")
            if live2d_prompt:
                logger.info(f"[{self.session_id}] 已添加 Live2D 表情提示词")
                logger.info(f"[{self.session_id}] Live2D 提示词长度: {len(live2d_prompt)} 字符")
                logger.info(f"[{self.session_id}] Live2D 提示词内容:\n{live2d_prompt}")
            else:
                logger.warning(f"[{self.session_id}] Live2D 提示词为空或未生成")
            logger.info(f"[{self.session_id}] System prompt 总长度: {len(system_prompt)} 字符")
            logger.info(f"[{self.session_id}] System prompt 前500字符:\n{system_prompt[:500]}...")
        else:
            system_prompt = self._build_system_prompt(agent_config, persona_config)

        # 使用类型安全的配置对象创建 LLM
        self.llm_engine = LLMFactory.create_from_config(
            config=llm_config,
            system_prompt=system_prompt
        )

        # 验证创建的 LLM 类型
        logger.info(f"[{self.session_id}] LLM 创建完成: {type(self.llm_engine).__name__}")

    async def init_local_llm(self, llm_config, app_config: AppConfig = None) -> None:
        """
        初始化本地LLM服务（用于简单应答，无persona）

        Args:
            llm_config: LLM配置
            app_config: 应用配置
        """
        if self.local_llm_engine is not None:
            logger.debug(f"[{self.session_id}] Local LLM 已初始化，跳过")
            return

        if llm_config is None:
            logger.info(f"[{self.session_id}] Local LLM 配置为空，跳过初始化")
            return

        logger.info(f"[{self.session_id}] 初始化本地LLM: {llm_config.type}/{llm_config.model}")

        # 本地LLM不需要系统提示词（清空system prompt）
        self.local_llm_engine = LLMFactory.create_from_config(
            config=llm_config,
            system_prompt=""  # 清空system prompt，只做简单应答
        )

        logger.info(f"[{self.session_id}] 本地LLM创建完成: {type(self.local_llm_engine).__name__}")

    def _get_live2d_prompt(self) -> Optional[str]:
        """
        获取 Live2D 表情提示词（如果启用）

        Returns:
            表情提示词字符串，如果未启用则返回 None
        """
        try:
            from .config.live2d import get_live2d_config
            from .live2d.prompt_builder import EmotionPromptBuilder

            live2d_config = get_live2d_config()

            if not live2d_config.enabled:
                return None

            # 使用 EmotionPromptBuilder 生成提示词
            builder = EmotionPromptBuilder.from_config({
                "valid_emotions": live2d_config.valid_emotions
            })
            return builder.build_prompt()

        except Exception as e:
            logger.warning(f"获取 Live2D 提示词失败: {e}")
            return None

    def _build_system_prompt(self, agent_config: AgentConfig, persona_config: PersonaConfig) -> str:
        """
        构建完整的系统提示词（备用方法）

        Args:
            agent_config: Agent 配置
            persona_config: 人设配置

        Returns:
            str: 完整的系统提示词
        """
        return persona_config.build_system_prompt()

    async def init_vad(self, vad_config: VADConfig) -> None:
        """
        初始化 VAD 服务（使用工厂模式）

        Args:
            vad_config: VAD 配置
        """
        if self.vad_engine is not None:
            logger.debug(f"[{self.session_id}] VAD 已初始化，跳过")
            return

        provider = vad_config.type
        logger.info(f"[{self.session_id}] 🔧 正在初始化 VAD 引擎: {provider}")

        # 使用 create_from_config 方法（与其他服务保持一致）
        try:
            self.vad_engine = VADFactory.create_from_config(vad_config)
            logger.info(f"[{self.session_id}] ✅ VAD 引擎创建成功: {type(self.vad_engine).__name__}")

            # 打印 VAD 配置（仅第一次）
            if hasattr(self.vad_engine, 'prob_threshold'):
                logger.info(f"[{self.session_id}] 📊 VAD 配置: "
                           f"prob_threshold={self.vad_engine.prob_threshold}, "
                           f"db_threshold={self.vad_engine.db_threshold}, "
                           f"required_hits={self.vad_engine.required_hits}, "
                           f"required_misses={self.vad_engine.required_misses}")

        except Exception as e:
            logger.error(f"[{self.session_id}] ❌ VAD 引擎创建失败: {e}")
            self.vad_engine = None

    async def init_memory(self) -> None:
        """
        初始化记忆系统

        从 config/features/memory.yaml 加载配置
        支持向量搜索（第二层个性化）
        """
        try:
            from pathlib import Path
            import yaml

            memory_config_path = Path(__file__).parent.parent.parent / "config" / "features" / "memory.yaml"

            if not memory_config_path.exists():
                logger.warning(f"[{self.session_id}] 记忆系统配置文件不存在: {memory_config_path}")
                return

            with open(memory_config_path, 'r', encoding='utf-8') as f:
                memory_config = yaml.safe_load(f)

            if not memory_config.get('memory', {}).get('enabled', False):
                logger.info(f"[{self.session_id}] 记忆系统未启用")
                return

            # 构建记忆系统配置
            config = {
                "short_term_max_turns": memory_config['memory']['short_term']['max_turns'],
                "long_term_db_path": memory_config['memory']['long_term']['db_path'],
                "importance_threshold": memory_config['memory']['importance']['threshold']
            }

            # 向量搜索配置（第二层个性化）
            vector_search_config = memory_config.get('memory', {}).get('vector_search', {})
            if vector_search_config.get('enabled', False):
                config['enable_vector_search'] = True
                config['vector_storage_path'] = vector_search_config.get('storage_path', 'E:/AnimaData/vector_db')
                config['embedding_model'] = vector_search_config.get('embedding_model', 'paraphrase-multilingual-MiniLM-L12-v2')

                logger.info(f"[{self.session_id}] 向量搜索已启用")
                logger.info(f"[{self.session_id}] 存储路径: {config['vector_storage_path']}")
                logger.info(f"[{self.session_id}] 嵌入模型: {config['embedding_model']}")

            self.memory_system = MemorySystem(config)
            logger.info(f"[{self.session_id}] ✅ 记忆系统初始化完成")

        except Exception as e:
            logger.warning(f"[{self.session_id}] 记忆系统初始化失败: {e}")
            logger.warning(f"[{self.session_id}] 错误详情: {type(e).__name__}: {str(e)}")
            self.memory_system = None

    # ========================================
    # 生命周期管理
    # ========================================

    async def close(self) -> None:
        """关闭并清理所有资源"""
        logger.info(f"[{self.session_id}] 正在关闭服务上下文...")

        if self.asr_engine:
            await self.asr_engine.close()
            self.asr_engine = None

        if self.tts_engine:
            await self.tts_engine.close()
            self.tts_engine = None

        if self.llm_engine:
            await self.llm_engine.close()
            self.llm_engine = None

        if self.vad_engine:
            await self.vad_engine.close()
            self.vad_engine = None

        if self.memory_system:
            self.memory_system.close()
            self.memory_system = None

        logger.info(f"[{self.session_id}] 服务上下文已关闭")

    # ========================================
    # 核心业务流程
    # ========================================

    async def process_text_input(self, text: str) -> str:
        """
        处理文本输入的完整流程

        Args:
            text: 用户输入的文本

        Returns:
            str: LLM 的回复
        """
        if not self.llm_engine:
            raise RuntimeError("LLM 未初始化")

        self.is_processing = True
        try:
            response = await self.llm_engine.chat(text)
            return response
        finally:
            self.is_processing = False

    async def process_audio_input(self, audio_data: bytes) -> str:
        """
        处理音频输入的完整流程
        ASR -> LLM -> TTS

        Args:
            audio_data: 音频数据

        Returns:
            str: 生成的音频文件路径
        """
        if not self.asr_engine or not self.agent_engine or not self.tts_engine:
            raise RuntimeError("服务未完全初始化")

        self.is_processing = True
        try:
            # 1. ASR: 语音转文字
            logger.debug(f"[{self.session_id}] ASR 处理中...")
            user_text = await self.asr_engine.transcribe(audio_data)
            logger.info(f"[{self.session_id}] ASR 结果: {user_text}")

            # 2. Agent: 生成回复
            logger.debug(f"[{self.session_id}] Agent 处理中...")
            agent_response = await self.agent_engine.chat(user_text)
            logger.info(f"[{self.session_id}] Agent 回复: {agent_response}")

            # 3. TTS: 文字转语音
            logger.debug(f"[{self.session_id}] TTS 处理中...")
            audio_path = await self.tts_engine.synthesize(agent_response)
            logger.info(f"[{self.session_id}] TTS 完成: {audio_path}")

            return audio_path

        finally:
            self.is_processing = False

    # ========================================
    # 配置切换
    # ========================================

    async def handle_config_switch(self, new_config: AppConfig) -> None:
        """
        处理配置切换

        Args:
            new_config: 新的配置
        """
        logger.info(f"[{self.session_id}] 切换配置...")

        # 关闭现有服务
        await self.close()

        # 使用新配置重新加载
        await self.load_from_config(new_config)

        logger.info(f"[{self.session_id}] 配置切换完成")