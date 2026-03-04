"""
对话编排器
整合 ASR, TTS, Agent 和 EventBus，使用 EventRouter 管理 Handler
使用 InputPipeline 和 OutputPipeline 处理数据流
"""

from typing import TYPE_CHECKING, Optional, Any, Union
from dataclasses import dataclass, field
from loguru import logger
import numpy as np
from datetime import datetime
import uuid

from anima.events.core import EventBus, EventRouter, EventPriority
from anima.core import EventType, OutputEvent
from anima.pipeline import InputPipeline, OutputPipeline
from anima.pipeline.steps import ASRStep, TextCleanStep, EmotionExtractionStep

if TYPE_CHECKING:
    from anima.services.asr import ASRInterface
    from anima.services.tts import TTSInterface
    from anima.services.llm import AgentInterface
    from anima.events.handlers import BaseHandler
    from anima.core import WebSocketSend, PipelineContext
    from anima.memory import MemorySystem


@dataclass
class ConversationResult:
    """对话处理结果"""
    success: bool = True
    response_text: str = ""
    audio_path: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class ConversationOrchestrator:
    """
    对话编排器
    
    整合对话流程：ASR -> Agent -> TTS
    使用 EventRouter 管理 Handler 的事件订阅
    使用 InputPipeline 处理输入
    使用 OutputPipeline 处理输出
    
    使用示例:
        orchestrator = ConversationOrchestrator(
            asr_engine=asr,
            tts_engine=tts,
            agent=agent,
            websocket_send=websocket_send,
            session_id="session-001",
        )
        
        # 注册 Handler
        orchestrator.register_handler("sentence", text_handler)
        
        # 启动编排器
        orchestrator.start()
        
        # 处理输入
        result = await orchestrator.process_input("你好")
        
        # 停止编排器
        orchestrator.stop()
    """
    
    def __init__(
        self,
        asr_engine: Optional["ASRInterface"] = None,
        tts_engine: Optional["TTSInterface"] = None,
        agent: Optional["AgentInterface"] = None,
        websocket_send: Optional["WebSocketSend"] = None,
        session_id: Optional[str] = None,
        live2d_config=None,
        memory_system: Optional["MemorySystem"] = None,
        local_llm: Optional["LLMInterface"] = None,
    ):
        """
        初始化对话编排器

        Args:
            asr_engine: ASR 引擎
            tts_engine: TTS 引擎
            agent: Agent 引擎（底座LLM，如GLM API）
            websocket_send: WebSocket 发送函数
            session_id: 会话 ID
            live2d_config: Live2D 配置（可选）
            memory_system: 记忆系统（可选）
            local_llm: 本地LLM（用于简单应答，无persona，可选）
        """
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        self.agent = agent
        self.session_id = session_id or "default"
        self.live2d_config = live2d_config
        self.memory_system = memory_system
        self.local_llm = local_llm

        # 包装 websocket_send（如果提供）以适配前端事件格式
        self.websocket_send = websocket_send
        if websocket_send is not None:
            from anima.events.handlers.socket_adapter import SocketEventAdapter
            adapter = SocketEventAdapter(websocket_send)
            self.websocket_send = adapter.send

        # 创建 EventBus 和 EventRouter
        self.event_bus = EventBus()
        self.event_router = EventRouter(self.event_bus)

        # 创建输入和输出管线
        self.input_pipeline = InputPipeline(event_bus=self.event_bus)
        self.output_pipeline = OutputPipeline(event_bus=self.event_bus)

        # 自动组装默认管线步骤
        self._setup_default_pipeline()

        # 状态
        self._is_running = False
        self._interrupted = False
        self._is_processing = False

        # 序列计数器（用于事件）
        self._seq_counter = 0
    
    def _setup_default_pipeline(self) -> None:
        """
        组装默认的管线步骤

        新架构（LocalLLM + 底座LLM）：
        1. ASRStep: 处理音频输入，转换为文本
        2. LocalLLMStep: 调用LocalLLM进行简单应答（无persona）
        3. TextCleanStep: 清洗和规范化文本

        输出管线：使用 OutputPipeline 的默认行为
        """
        # 输入管线步骤
        if self.asr_engine:
            asr_step = ASRStep(
                asr_engine=self.asr_engine,
                websocket_send=self.websocket_send,
            )
            self.input_pipeline.add_step(asr_step)
            logger.debug(f"[{self.session_id}] 添加输入步骤: ASRStep")

        # LocalLLM步骤（如果本地LLM可用）
        if self.local_llm:
            from anima.pipeline.steps.local_llm_step import LocalLLMStep

            local_llm_step = LocalLLMStep(
                local_llm=self.local_llm
            )
            self.input_pipeline.add_step(local_llm_step)
            logger.info(f"[{self.session_id}] 添加输入步骤: LocalLLMStep 🤖 (无persona)")

        text_clean_step = TextCleanStep()
        self.input_pipeline.add_step(text_clean_step)
        logger.debug(f"[{self.session_id}] 添加输入步骤: TextCleanStep")
    
    def register_handler(
        self,
        event_type: str,
        handler: "BaseHandler",
        priority: int = EventPriority.NORMAL,
    ) -> "ConversationOrchestrator":
        """
        注册 Handler 到事件类型
        
        Args:
            event_type: 事件类型（如 "sentence", "audio", "tool_call"）
            handler: Handler 实例
            priority: 优先级
            
        Returns:
            self（支持链式调用）
        """
        self.event_router.register(event_type, handler, priority)
        logger.debug(
            f"[{self.session_id}] 注册 Handler: "
            f"{event_type} -> {handler.__class__.__name__}"
        )
        return self
    
    def register_many(
        self,
        event_types: list,
        handler: "BaseHandler",
        priority: int = EventPriority.NORMAL,
    ) -> "ConversationOrchestrator":
        """
        将同一个 Handler 注册到多个事件类型
        
        Args:
            event_types: 事件类型列表
            handler: Handler 实例
            priority: 优先级
            
        Returns:
            self
        """
        self.event_router.register_many(event_types, handler, priority)
        return self
    
    def add_input_step(self, step) -> "ConversationOrchestrator":
        """
        添加输入管线步骤
        
        Args:
            step: PipelineStep 实例
            
        Returns:
            self（支持链式调用）
        """
        self.input_pipeline.add_step(step)
        return self
    
    def add_output_step(self, step) -> "ConversationOrchestrator":
        """
        添加输出管线步骤
        
        Args:
            step: PipelineStep 实例
            
        Returns:
            self（支持链式调用）
        """
        self.output_pipeline.add_step(step)
        return self
    
    def start(self) -> None:
        """启动编排器（连接 EventRouter 到 EventBus）"""
        if self._is_running:
            logger.warning(f"[{self.session_id}] 编排器已在运行")
            return
        
        self.event_router.setup()
        self._is_running = True
        self._interrupted = False
        logger.info(f"[{self.session_id}] 编排器已启动")
    
    def stop(self) -> None:
        """停止编排器（清理所有订阅）"""
        self.event_router.clear()
        self._is_running = False
        logger.info(f"[{self.session_id}] 编排器已停止")
    
    def interrupt(self) -> None:
        """打断当前处理"""
        self._interrupted = True
        self.output_pipeline.interrupt()

        # 发送惊讶表情（同步版本，用于非异步上下文）
        self._emit_expression_sync("surprised")

        logger.info(f"[{self.session_id}] 编排器收到打断信号")
    
    async def process_input(
        self,
        raw_input: Union[str, np.ndarray],
        metadata: Optional[dict] = None,
        from_name: str = "User",
    ) -> ConversationResult:
        """
        处理输入（文本或音频）
        
        Args:
            raw_input: 输入内容（文本字符串或音频 numpy 数组）
            metadata: 元数据
            from_name: 发送者名称
            
        Returns:
            ConversationResult: 处理结果
        """
        if not self._is_running:
            logger.warning(f"[{self.session_id}] 编排器未启动，自动启动")
            self.start()
        
        self._is_processing = True
        self._interrupted = False
        self.output_pipeline.reset()
        
        try:
            # 使用 InputPipeline 处理输入
            ctx = await self.input_pipeline.execute(
                raw_input=raw_input,
                metadata=metadata,
                from_name=from_name,
            )
            
            # 检查是否有错误
            if ctx.error:
                return ConversationResult(
                    success=False,
                    error=ctx.error
                )
            
            # 检查是否被中断
            if self._interrupted:
                return ConversationResult(
                    success=False,
                    error="处理被中断",
                    metadata={"interrupted": True}
                )
            
            # 获取处理后的文本
            text = ctx.text
            if not text:
                return ConversationResult(
                    success=False,
                    error="无法获取有效的输入文本"
                )
            
            # 处理对话
            result = await self._process_conversation(ctx, text)
            
            return result
            
        except Exception as e:
            logger.error(f"[{self.session_id}] 处理输入时出错: {e}")
            return ConversationResult(
                success=False,
                error=str(e)
            )
        finally:
            self._is_processing = False
    
    async def _process_conversation(
        self,
        ctx: "PipelineContext",
        text: str,
    ) -> ConversationResult:
        """
        处理对话核心逻辑

        Args:
            ctx: 管线上下文
            text: 输入文本

        Returns:
            ConversationResult
        """
        if not self.agent:
            return ConversationResult(
                success=False,
                error="Agent 未初始化"
            )

        logger.info(f"[{self.session_id}] 处理对话: {text[:50]}...")

        # 📚 检索相关记忆（如果记忆系统可用）
        original_text = text
        if self.memory_system:
            try:
                related_memories = await self.memory_system.retrieve_context(
                    query=text,
                    session_id=self.session_id,
                    max_turns=3
                )

                if related_memories:
                    logger.info(f"[{self.session_id}] 检索到 {len(related_memories)} 条相关记忆")

                    # 格式化记忆为上下文
                    memory_context = self._format_memory_context(related_memories)

                    # 将记忆注入到输入文本中，并明确指示LLM使用这些信息
                    text = f"""【重要提示】以下是与当前对话相关的历史记录，请仔细阅读并参考这些信息来回答用户的问题。如果用户询问相关信息，你必须基于这些历史记录来回答。

[相关历史对话]
{memory_context}

[当前对话]
{text}"""
                    logger.debug(f"[{self.session_id}] 记忆上下文已注入")
            except Exception as e:
                logger.warning(f"[{self.session_id}] 记忆检索失败: {e}")

        # 发送思考表情
        await self._emit_expression("thinking")

        # 如果启用了 Live2D，在消息末尾添加表情标签提醒
        if self.live2d_config and self.live2d_config.enabled:
            # 【方案 A】使用强烈的提醒语气
            emotion_hint = "\n\n【重要】你必须使用表情标签（如 [happy]、[sad]、[angry]、[surprised]、[thinking]、[neutral]）来表达情感！这是强制要求，每条回复必须至少包含 1-2 个表情标签。表情标签会自动从语音中移除，不影响 TTS 发音。示例：你好！[happy] 很高兴见到你！"
            text = f"{text}{emotion_hint}"
            logger.info(f"[{self.session_id}] 添加强制表情标签提醒")

        # 获取 Agent 响应流
        agent_stream = self.agent.chat_stream(text)

        # 发送说话表情
        await self._emit_expression("speaking")

        # 使用 OutputPipeline 处理响应流
        response_text = await self.output_pipeline.process(ctx, agent_stream)

        if self._interrupted:
            return ConversationResult(
                success=False,
                error="处理被中断",
                metadata={"interrupted": True}
            )

        # 提取表情标签（如果 Live2D 配置存在）
        emotions = []
        if self.live2d_config and self.live2d_config.enabled:
            logger.info(f"[{self.session_id}] Live2D 已启用，开始提取表情标签")
            logger.debug(f"[{self.session_id}] 响应文本: {response_text[:100]}...")

            emotion_step = EmotionExtractionStep(
                valid_emotions=self.live2d_config.valid_emotions
            )
            await emotion_step(ctx)
            emotions = ctx.metadata.get("emotions", [])

            logger.info(f"[{self.session_id}] 提取到 {len(emotions)} 个表情标签: {emotions}")

            # response_text 已被清理为不含表情标签的文本
            response_text = ctx.response
        else:
            logger.warning(f"[{self.session_id}] Live2D 未启用或配置不存在")

        # 如果有 TTS，生成音频
        audio_path = None
        if self.tts_engine and not self._interrupted:
            audio_path = await self._synthesize_audio(response_text, emotions)

        # 📚 存储对话到记忆系统（如果记忆系统可用）
        if self.memory_system:
            try:
                from anima.memory import MemoryTurn

                # 创建记忆轮次
                memory_turn = MemoryTurn(
                    turn_id=str(uuid.uuid4()),
                    session_id=self.session_id,
                    timestamp=datetime.now(),
                    user_input=original_text,
                    agent_response=response_text,
                    emotions=emotions,
                    metadata={
                        "audio_path": audio_path,
                        "interrupted": self._interrupted
                    }
                )

                # 存储到记忆系统
                await self.memory_system.store_turn(memory_turn)
                logger.info(f"[{self.session_id}] 对话已存储到记忆系统 (重要性: {memory_turn.importance:.2f})")

            except Exception as e:
                logger.warning(f"[{self.session_id}] 记忆存储失败: {e}")

        # 发送空闲表情
        await self._emit_expression("idle")

        return ConversationResult(
            success=True,
            response_text=response_text,
            audio_path=audio_path,
        )
    
    async def _synthesize_audio(
        self,
        text: str,
        emotions: list = None
    ) -> Optional[str]:
        """
        使用 TTS 合成音频

        Args:
            text: 要合成的文本
            emotions: 表情标签列表（可选）

        Returns:
            音频文件路径或 None
        """
        if not self.tts_engine:
            return None

        if emotions is None:
            emotions = []

        try:
            audio_path = await self.tts_engine.synthesize(text)
            logger.info(f"[{self.session_id}] TTS 完成: {audio_path}")
            logger.info(f"[{self.session_id}] 表情标签数量: {len(emotions)}, 内容: {emotions}")

            # 如果有表情标签，发送统一的 audio_with_expression 事件
            if self.live2d_config and self.live2d_config.enabled:
                await self._emit_audio_with_expression(
                    audio_path=audio_path,
                    emotions=emotions,
                    text=text
                )
            else:
                # 否则发送普通的音频事件
                logger.warning(f"[{self.session_id}] Live2D 未启用，发送普通音频事件")
                await self._emit_event(EventType.AUDIO, {"path": audio_path})

            return audio_path
        except Exception as e:
            logger.error(f"[{self.session_id}] TTS 合成失败: {e}")
            return None

    async def _emit_audio_with_expression(
        self,
        audio_path: str,
        emotions: list,
        text: str
    ) -> None:
        """
        发送音频 + 表情统一事件

        Args:
            audio_path: 音频文件路径
            emotions: 表情标签列表
            text: 文本内容
        """
        from anima.core.events import EventType

        event_data = {
            "audio_path": audio_path,
            "emotions": emotions,
            "text": text,
        }

        event = OutputEvent(
            type=EventType.AUDIO_WITH_EXPRESSION,
            data=event_data,
            seq=self._seq_counter,
            metadata={}
        )

        await self.event_bus.emit(event)
        self._seq_counter += 1

        logger.info(
            f"[{self.session_id}] 发送 audio_with_expression 事件: "
            f"{len(emotions)} 个表情"
        )
    
    async def _emit_event(self, event_type: str, data: Any) -> None:
        """
        发送事件到 EventBus

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        from anima.core import OutputEvent

        event = OutputEvent(
            type=event_type,
            data=data,
        )

        await self.event_bus.emit(event)

    async def _emit_expression(self, expression: str) -> None:
        """
        发送表情事件到 EventBus（异步版本）

        Args:
            expression: 表情名称
        """
        from anima.core import OutputEvent
        import time

        logger.info(f"[{self.session_id}] 🎭 正在发送表情事件: {expression}")

        event = OutputEvent(
            type=EventType.EXPRESSION,
            data=expression,
            seq=self._seq_counter,
            metadata={"timestamp": time.time()}
        )

        await self.event_bus.emit(event)
        self._seq_counter += 1
        logger.info(f"[{self.session_id}] ✅ 表情事件已发送: {expression}")

    def _emit_expression_sync(self, expression: str) -> None:
        """
        发送表情事件到 EventBus（同步版本，用于非异步上下文）

        Args:
            expression: 表情名称
        """
        from anima.core import OutputEvent
        import time
        import asyncio

        event = OutputEvent(
            type=EventType.EXPRESSION,
            data=expression,
            seq=self._seq_counter,
            metadata={"timestamp": time.time()}
        )

        # 在同步上下文中，创建任务来发送事件
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self.event_bus.emit(event))
            self._seq_counter += 1
            logger.debug(f"[{self.session_id}] 发送表情（同步）: {expression}")
        except RuntimeError:
            # 如果没有事件循环，无法发送
            logger.debug(f"[{self.session_id}] 无法发送表情事件：没有事件循环")
    
    @property
    def is_running(self) -> bool:
        """编排器是否正在运行"""
        return self._is_running
    
    @property
    def is_processing(self) -> bool:
        """是否正在处理输入"""
        return self._is_processing
    
    def get_handler_count(self) -> int:
        """获取已注册的 Handler 数量"""
        return self.event_router.handler_count

    def _format_memory_context(self, memories) -> str:
        """
        格式化记忆为上下文字符串

        Args:
            memories: MemoryTurn 列表

        Returns:
            str: 格式化的记忆上下文
        """
        if not memories:
            return ""

        lines = []
        for i, mem in enumerate(memories, 1):
            # 只显示最近几条对话的摘要
            user_input = mem.user_input[:100] + "..." if len(mem.user_input) > 100 else mem.user_input
            agent_response = mem.agent_response[:100] + "..." if len(mem.agent_response) > 100 else mem.agent_response

            lines.append(f"{i}. 用户: {user_input}")
            lines.append(f"   AI: {agent_response}")

        return "\n".join(lines)