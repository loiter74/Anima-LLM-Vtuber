"""
Socket.IO 服务端实现
基于 python-socketio 库，使用 ServiceContext 管理服务
参考 Open-LLM-VTuber 的实时对话逻辑

重构：使用 ConversationOrchestrator 整合对话逻辑
"""

import os
from pathlib import Path
from loguru import logger

# 加载 .env 文件中的环境变量（必须在其他导入之前）
try:
    from dotenv import load_dotenv
    # 获取项目根目录（socketio_server.py 的上上级目录，因为 src/anima/socketio_server.py）
    env_path = Path(__file__).parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
        logger.info(f"✅ 已加载环境变量文件: {env_path}")
        # 立即验证关键环境变量
        glm_key = os.getenv("GLM_API_KEY")
        if glm_key:
            logger.info(f"✅ GLM_API_KEY 已从 .env 加载: {glm_key[:20]}... (长度: {len(glm_key)})")
        else:
            logger.error("⚠️ .env 文件已加载，但 GLM_API_KEY 仍未设置！")
    else:
        logger.warning(f".env 文件不存在: {env_path}，将使用系统环境变量")
except ImportError:
    # 如果没有安装 python-dotenv，跳过（依赖系统环境变量）
    logger.info("python-dotenv 未安装，使用系统环境变量")
    pass

# 最终验证关键环境变量
glm_key = os.getenv("GLM_API_KEY")
if glm_key:
    logger.info(f"✅ GLM_API_KEY 在运行时可用: {glm_key[:20]}...")
else:
    logger.error("⚠️ GLM_API_KEY 在运行时不可用，GLM将降级到MockLLM")

import socketio
import json
import numpy as np
from fastapi import FastAPI
import uvicorn
from typing import Dict, Union, Optional

from anima.config import AppConfig
from anima.service_context import ServiceContext
from anima.services.conversation import (
    ConversationOrchestrator,
    SessionManager,
)
from anima.handlers import TextHandler, AudioHandler
from anima.eventbus import EventPriority

# 创建 Socket.IO 服务器
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=['http://localhost:3000', 'http://127.0.0.1:3000', '*'],
    cors_credentials=True,
)

# 创建 FastAPI 应用
app = FastAPI(title="Anima - AI Virtual Companion")

# 将 Socket.IO 挂载到 FastAPI
socket_app = socketio.ASGIApp(sio, app)

# ============================================
# 全局状态管理
# ============================================

# 存储每个会话的 ServiceContext
# 键: session_id, 值: ServiceContext 实例
session_contexts: Dict[str, ServiceContext] = {}

# 存储每个会话的 ConversationOrchestrator
# 键: session_id, 值: ConversationOrchestrator 实例
orchestrators: Dict[str, ConversationOrchestrator] = {}

# 音频缓冲区（简单实现）
audio_buffers: Dict[str, list] = {}

# VAD 超时追踪（防止VAD一直检测不到语音结束）
# 键: session_id, 值: {'active_time': 最后活跃时间戳, 'chunk_count': 接收的音频块数}
vad_active_sessions: Dict[str, dict] = {}

# 全局配置（可被所有会话共享）
global_config: AppConfig = None

# VAD 超时设置（秒）
VAD_TIMEOUT_SECONDS = 15  # 如果VAD持续活跃超过15秒，强制触发ASR


class AudioBufferManager:
    """音频缓冲区管理器"""
    
    def append(self, sid: str, audio_data) -> int:
        """追加音频数据"""
        if sid not in audio_buffers:
            audio_buffers[sid] = []
        
        if isinstance(audio_data, list):
            audio_buffers[sid].extend(audio_data)
        else:
            audio_buffers[sid].append(audio_data)
        
        return len(audio_buffers[sid])
    
    def pop(self, sid: str) -> Optional[np.ndarray]:
        """获取并清空缓冲区"""
        if sid not in audio_buffers:
            return None
        
        data = audio_buffers.pop(sid)
        if not data:
            return None
        
        return np.array(data, dtype=np.float32)
    
    def remove(self, sid: str) -> None:
        """移除缓冲区"""
        audio_buffers.pop(sid, None)


# 音频缓冲区管理器实例
audio_buffer_manager = AudioBufferManager()


async def get_or_create_context(sid: str) -> ServiceContext:
    """
    获取或创建指定会话的 ServiceContext

    Args:
        sid: session id

    Returns:
        ServiceContext: 该会话的服务上下文
    """
    if sid not in session_contexts:
        print(f"\n[{sid}] 🔧 创建新的 ServiceContext")
        ctx = ServiceContext()
        ctx.session_id = sid

        # 设置发送消息的回调函数
        async def send_text_callback(message: str):
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message
            await sio.emit(data.get('type', 'message'), data, to=sid)

        ctx.send_text = send_text_callback

        # 加载配置（使用全局配置或默认配置）
        print(f"[{sid}] 📋 加载配置...")
        config = global_config or AppConfig.load()
        await ctx.load_from_config(config)

        session_contexts[sid] = ctx
        print(f"[{sid}] ✅ ServiceContext 创建完成")
        logger.info(f"为会话 {sid} 创建了新的 ServiceContext")
    else:
        # print(f"\n[{sid}] ♻️ 使用现有 ServiceContext")  # 注释掉以减少日志噪音
        pass

    return session_contexts[sid]


async def get_or_create_orchestrator(sid: str) -> ConversationOrchestrator:
    """
    获取或创建指定会话的 ConversationOrchestrator

    Args:
        sid: session id

    Returns:
        ConversationOrchestrator: 该会话的对话编排器
    """
    if sid not in orchestrators:
        logger.info(f"[{sid}] 创建新的 ConversationOrchestrator")
        ctx = await get_or_create_context(sid)
        
        # WebSocket 发送函数
        async def websocket_send(message: str):
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message
            await sio.emit(data.get('type', 'message'), data, to=sid)
        
        # 创建编排器（管线步骤在编排器内部自动组装）
        orchestrator = ConversationOrchestrator(
            asr_engine=ctx.asr_engine,
            tts_engine=ctx.tts_engine,
            agent=ctx.llm_engine,
            websocket_send=websocket_send,
            session_id=sid,
        )
        
        # 创建并注册 TextHandler（使用 EventRouter）
        text_handler = TextHandler(websocket_send=websocket_send)
        logger.info(f"[{sid}] 创建 TextHandler 实例: ID={id(text_handler)}")
        orchestrator.register_handler("sentence", text_handler, priority=EventPriority.NORMAL)
        logger.info(f"[{sid}] TextHandler 已注册到 sentence 事件")

        # 创建并注册 AudioHandler
        audio_handler = AudioHandler(websocket_send=websocket_send)
        orchestrator.register_handler("audio", audio_handler, priority=EventPriority.NORMAL)

        # 启动编排器（将 EventRouter 连接到 EventBus）
        orchestrator.start()
        
        orchestrators[sid] = orchestrator
        logger.info(f"为会话 {sid} 创建了新的 ConversationOrchestrator，已注册 {orchestrator.get_handler_count()} 个 Handler")
    
    return orchestrators[sid]


async def cleanup_context(sid: str) -> None:
    """
    清理指定会话的所有资源
    
    Args:
        sid: session id
    """
    # 停止编排器（清理 EventRouter 中的所有订阅）
    if sid in orchestrators:
        orchestrator = orchestrators[sid]
        orchestrator.stop()
        del orchestrators[sid]
    
    # 清理音频缓冲区
    audio_buffer_manager.remove(sid)
    
    # 清理上下文
    if sid in session_contexts:
        ctx = session_contexts[sid]
        await ctx.close()
        del session_contexts[sid]
        logger.info(f"已清理会话 {sid} 的所有资源")


async def _process_audio_input(sid: str) -> None:
    """
    处理音频输入的辅助函数

    从缓冲区获取音频数据并通过 ConversationOrchestrator 处理
    """
    try:
        # 获取累积的音频数据
        audio_data = audio_buffer_manager.pop(sid)

        if audio_data is None or len(audio_data) == 0:
            logger.warning(f"[{sid}] _process_audio_input: 没有音频数据")
            await sio.emit('control', {
                'type': 'control',
                'text': 'no-audio-data'
            }, to=sid)
            return

        audio_duration = len(audio_data) / 16000  # 假设 16kHz
        logger.info(f"[{sid}] 🎙️ 开始处理音频，时长: {audio_duration:.2f}秒")

        # 发送 conversation-start 信号，通知前端暂停发送音频
        await sio.emit('control', {
            'type': 'control',
            'text': 'conversation-start'
        }, to=sid)

        orchestrator = await get_or_create_orchestrator(sid)

        # 使用编排器处理音频输入
        result = await orchestrator.process_input(
            raw_input=audio_data,
            metadata={},
            from_name='User',
        )

        if result.error:
            logger.error(f"[{sid}] 处理出错: {result.error}")
            await sio.emit('error', {
                'type': 'error',
                'message': result.error
            }, to=sid)
            # 出错时也发送 conversation-end，恢复前端监听
            await sio.emit('control', {
                'type': 'control',
                'text': 'conversation-end'
            }, to=sid)
        else:
            logger.info(f"[{sid}] ✅ 音频处理完成")
            # 发送 conversation-end 信号，通知前端恢复监听
            await sio.emit('control', {
                'type': 'control',
                'text': 'conversation-end'
            }, to=sid)

    except Exception as e:
        logger.error(f"[{sid}] _process_audio_input 出错: {e}", exc_info=True)
        await sio.emit('error', {
            'type': 'error',
            'message': str(e)
        }, to=sid)
        # 出错时也发送 conversation-end，恢复前端监听
        await sio.emit('control', {
            'type': 'control',
            'text': 'conversation-end'
        }, to=sid)


# ============================================
# 连接事件处理
# ============================================

@sio.event
async def connect(sid, environ):
    """
    客户端连接时触发
    """
    print(f"\n{'='*60}")
    print(f"✅ 客户端已连接: {sid}")
    print(f"{'='*60}\n")
    logger.info(f"客户端已连接: {sid}")

    # 发送欢迎消息
    await sio.emit('connection-established', {
        'message': '连接成功',
        'sid': sid
    }, to=sid)

    # 发送启动麦克风信号
    await sio.emit('control', {
        'type': 'control',
        'text': 'start-mic'
    }, to=sid)
    print(f"📤 已发送 start-mic 信号给客户端 {sid}")


@sio.event
async def disconnect(sid):
    """
    客户端断开时触发
    """
    logger.info(f"客户端已断开: {sid}")
    
    # 清理该会话的所有资源
    await cleanup_context(sid)


# ============================================
# 业务事件处理
# ============================================

@sio.event
async def text_input(sid, data):
    """
    处理文本输入
    使用 ConversationOrchestrator 处理对话
    """
    text = data.get('text', '')
    logger.info(f"[{sid}] 收到文本输入: {text}")
    
    if not text:
        return
    
    try:
        orchestrator = await get_or_create_orchestrator(sid)
        
        # 使用编排器处理输入
        result = await orchestrator.process_input(
            raw_input=text,
            metadata=data.get('metadata', {}),
            from_name=data.get('from_name', 'User'),
        )
        
        if result.error:
            logger.error(f"[{sid}] 处理出错: {result.error}")
            await sio.emit('error', {
                'type': 'error',
                'message': result.error
            }, to=sid)
        
    except Exception as e:
        logger.error(f"[{sid}] 处理文本输入时出错: {e}")
        await sio.emit('error', {
            'type': 'error',
            'message': str(e)
        }, to=sid)


@sio.event
async def mic_audio_data(sid, data):
    """
    处理音频数据流
    将音频数据累积到缓冲区
    """
    audio = data.get('audio', [])
    
    if audio:
        sample_count = audio_buffer_manager.append(sid, audio)
        logger.debug(f"[{sid}] 累积音频: {len(audio)} 个采样点, 总计: {sample_count}")


@sio.event
async def raw_audio_data(sid, data):
    """
    处理原始音频数据用于 VAD 检测
    参考 Open-LLM-VTuber 的 _handle_raw_audio_data 实现
    """
    audio_chunk = data.get('audio', [])

    if not audio_chunk:
        logger.debug(f"[{sid}] 收到空音频数据")
        return

    # 静态计数器（用于日志）
    if not hasattr(raw_audio_data, 'counter'):
        raw_audio_data.counter = {}
    if sid not in raw_audio_data.counter:
        raw_audio_data.counter[sid] = 0
    raw_audio_data.counter[sid] += 1

    # 导入 numpy（在条件块之前，确保后续代码可以使用）
    import numpy as np

    # 每 10 个块打印一次音频统计信息（更频繁）
    count = raw_audio_data.counter[sid]
    if count % 10 == 1:
        audio_arr = np.array(audio_chunk)
        audio_min = float(np.min(audio_arr)) if len(audio_arr) > 0 else 0
        audio_max = float(np.max(audio_arr)) if len(audio_arr) > 0 else 0
        audio_mean = float(np.mean(np.abs(audio_arr))) if len(audio_arr) > 0 else 0
        audio_rms = float(np.sqrt(np.mean(audio_arr**2))) if len(audio_arr) > 0 else 0

        print(f"\n[{sid}] Audio chunk #{count}: {len(audio_chunk)} samples")
        print(f"  Range: [{audio_min:.2f}, {audio_max:.2f}], Mean: {audio_mean:.2f}, RMS: {audio_rms:.2f}")
        logger.info(f"[{sid}] Audio chunk #{count}: {len(audio_chunk)} samples, range=[{audio_min:.2f}, {audio_max:.2f}], mean={audio_mean:.2f}, rms={audio_rms:.2f}")

    try:
        ctx = await get_or_create_context(sid)

        # 检查是否有 VAD 引擎
        if ctx.vad_engine is None:
            # 没有 VAD，直接累积音频
            audio_buffer_manager.append(sid, audio_chunk)
            if count % 100 == 1:
                logger.warning(f"[{sid}] ⚠️ VAD 引擎未初始化，直接累积音频: {len(audio_chunk)} 采样点")
            return

        # 使用 VAD 检测语音（返回 VADResult 对象，不是可迭代对象）
        result = ctx.vad_engine.detect_speech(audio_chunk)

        # 记录 VAD 状态（降低频率，避免刷屏）
        # if count % 50 == 0 or result.state.value != 'IDLE':
        #     logger.info(f"[{sid}] 📊 VAD 状态: {result.state.value}, 音频块: {len(audio_chunk)} 采样点 (第 {count} 块)")

        # 🔥 超时保护：追踪VAD活跃时间
        import time
        current_time = time.time()

        if result.state.value == 'ACTIVE':
            # VAD 检测到语音，记录活跃时间
            if sid not in vad_active_sessions:
                vad_active_sessions[sid] = {'active_time': current_time, 'chunk_count': 0}
            vad_active_sessions[sid]['chunk_count'] += 1

            # 检查是否超时（防止VAD一直检测不到语音结束）
            active_duration = current_time - vad_active_sessions[sid]['active_time']
            if active_duration > VAD_TIMEOUT_SECONDS:
                logger.warning(f"[{sid}] ⏰ VAD 持续活跃超过 {VAD_TIMEOUT_SECONDS} 秒，强制触发语音结束")

                # 清除超时记录
                if sid in vad_active_sessions:
                    del vad_active_sessions[sid]

                # 手动触发语音结束处理
                # 从 VAD 状态机获取累积的音频数据
                if hasattr(ctx.vad_engine, 'state_machine') and ctx.vad_engine.state_machine.bytes:
                    audio_data_bytes = bytes(ctx.vad_engine.state_machine.bytes)

                    if len(audio_data_bytes) > 1024:  # 至少有一些音频数据
                        logger.info(f"[{sid}] 🚨 超时强制触发ASR，音频长度: {len(audio_data_bytes)} 字节")

                        # 转换为 float32
                        audio_float = np.frombuffer(audio_data_bytes, dtype=np.int16).astype(np.float32) / 32767.0
                        audio_buffer_manager.append(sid, audio_float.tolist())

                        # 重置 VAD 状态机
                        ctx.vad_engine.reset()

                        # 发送控制信号
                        await sio.emit('control', {
                            'type': 'control',
                            'text': 'mic-audio-end'
                        }, to=sid)

                        # 触发对话处理
                        await _process_audio_input(sid)

        elif result.state.value == 'IDLE' and sid in vad_active_sessions:
            # VAD 回到空闲状态，清除超时记录
            del vad_active_sessions[sid]

        # 处理检测结果
        if result.is_speech_start:
            # 检测到语音开始
            logger.info(f"[{sid}] ✅ VAD 检测到语音开始")

        elif result.is_speech_end and len(result.audio_data) > 1024:
            # 检测到语音结束，保存音频并触发对话
            logger.info(f"[{sid}] ✅ VAD 检测到语音结束，音频长度: {len(result.audio_data)} 字节")

            # 清除超时记录
            if sid in vad_active_sessions:
                del vad_active_sessions[sid]

            # 将 int16 字节流转换为归一化的 float32（范围：[-1.0, 1.0]）
            audio_data = np.frombuffer(result.audio_data, dtype=np.int16).astype(np.float32) / 32767.0
            audio_buffer_manager.append(sid, audio_data.tolist())

            # 发送控制信号通知前端
            await sio.emit('control', {
                'type': 'control',
                'text': 'mic-audio-end'
            }, to=sid)

            # 直接触发对话处理（不需要等前端发送 mic_audio_end）
            await _process_audio_input(sid)
                
    except Exception as e:
        logger.error(f"[{sid}] VAD 处理出错: {e}", exc_info=True)


@sio.event
async def mic_audio_end(sid, data):
    """
    用户说完话，触发完整对话流程
    使用 ConversationOrchestrator 处理
    """
    logger.info(f"[{sid}] 音频输入结束")
    
    try:
        # 获取累积的音频数据
        audio_data = audio_buffer_manager.pop(sid)
        
        if audio_data is None or len(audio_data) == 0:
            logger.warning(f"[{sid}] 没有音频数据")
            await sio.emit('control', {
                'type': 'control',
                'text': 'no-audio-data'
            }, to=sid)
            return
        
        audio_duration = len(audio_data) / 16000  # 假设 16kHz
        logger.info(f"[{sid}] 音频时长: {audio_duration:.2f}秒")
        
        orchestrator = await get_or_create_orchestrator(sid)
        
        # 使用编排器处理音频输入
        result = await orchestrator.process_input(
            raw_input=audio_data,
            metadata=data.get('metadata', {}),
            from_name=data.get('from_name', 'User'),
        )
        
        if result.error:
            logger.error(f"[{sid}] 处理出错: {result.error}")
            await sio.emit('error', {
                'type': 'error',
                'message': result.error
            }, to=sid)
        
    except Exception as e:
        logger.error(f"[{sid}] 处理音频时出错: {e}")
        await sio.emit('error', {
            'type': 'error',
            'message': str(e)
        }, to=sid)


@sio.event
async def interrupt_signal(sid, data):
    """
    打断信号
    取消当前正在进行的对话和 TTS
    """
    # 获取用户听到的部分回复
    heard_response = data.get('text', '')
    logger.info(f"[{sid}] 收到打断信号，已听到的回复: {heard_response[:50] if heard_response else '(空)'}...")
    
    # 打断编排器（interrupt() 是同步方法，不需要 await）
    if sid in orchestrators:
        orchestrator = orchestrators[sid]
        orchestrator.interrupt()
    
    # 更新上下文状态
    if sid in session_contexts:
        session_contexts[sid].is_speaking = False
    
    await sio.emit('control', {
        'type': 'control',
        'text': 'interrupted'
    }, to=sid)


@sio.event
async def fetch_history_list(sid, data):
    """
    获取聊天历史列表
    """
    logger.info(f"[{sid}] 请求聊天历史列表")
    
    # TODO: 从持久化存储获取历史列表
    histories = [
        {'uid': 'history_001', 'preview': '你好...'},
        {'uid': 'history_002', 'preview': '今天天气...'},
    ]
    
    await sio.emit('history-list', {
        'type': 'history-list',
        'histories': histories
    }, to=sid)


@sio.event
async def fetch_history(sid, data):
    """
    获取特定历史记录
    """
    history_uid = data.get('history_uid')
    logger.info(f"[{sid}] 请求历史记录: {history_uid}")
    
    # TODO: 从持久化存储获取历史记录
    messages = [
        {'role': 'user', 'content': '你好'},
        {'role': 'assistant', 'content': '你好！有什么可以帮助你的吗？'},
    ]
    
    await sio.emit('history-data', {
        'type': 'history-data',
        'messages': messages
    }, to=sid)


@sio.event
async def switch_config(sid, data):
    """
    切换配置
    """
    config_name = data.get('file', 'default')
    logger.info(f"[{sid}] 切换配置: {config_name}")
    
    try:
        # 清理旧的编排器（保留上下文）
        if sid in orchestrators:
            del orchestrators[sid]
        
        # TODO: 加载新配置
        # new_config = load_config(config_name)
        # await ctx.handle_config_switch(new_config)
        
        await sio.emit('config-switched', {
            'type': 'config-switched',
            'message': f'已切换到配置: {config_name}'
        }, to=sid)
        
    except Exception as e:
        logger.error(f"[{sid}] 切换配置时出错: {e}")
        await sio.emit('error', {
            'type': 'error',
            'message': str(e)
        }, to=sid)


@sio.event
async def clear_history(sid, data):
    """
    清空对话历史
    """
    logger.info(f"[{sid}] 清空对话历史")
    
    ctx = await get_or_create_context(sid)
    if ctx.llm_engine:
        ctx.llm_engine.clear_history()
        logger.info(f"[{sid}] 对话历史已清空")
        
        await sio.emit('history-cleared', {
            'type': 'history-cleared'
        }, to=sid)


@sio.event
async def create_new_history(sid, data):
    """
    创建新的对话历史
    """
    logger.info(f"[{sid}] 创建新对话历史")
    
    # TODO: 创建新的历史记录
    
    await sio.emit('new-history-created', {
        'type': 'new-history-created',
        'history_uid': 'new_history_001'
    }, to=sid)


# ============================================
# 心跳检测
# ============================================

@sio.event
async def heartbeat(sid, data):
    """心跳检测"""
    await sio.emit('heartbeat-ack', {}, to=sid)


# ============================================
# 启动入口
# ============================================

def init_config(config_path: str = None) -> None:
    """
    初始化全局配置
    
    Args:
        config_path: YAML 配置文件路径（可选）
    """
    global global_config
    
    if config_path:
        global_config = AppConfig.from_yaml(config_path)
    else:
        # 默认从 config/config.yaml 加载
        global_config = AppConfig.load()
    
    logger.info(f"配置加载完成: {global_config.system.host}:{global_config.system.port}")


if __name__ == '__main__':
    import sys
    
    # 解析命令行参数
    config_file = None
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    
    # 初始化配置
    init_config(config_file)
    
    logger.info("启动 Socket.IO 服务器...")
    logger.info(f"访问 http://{global_config.system.host}:{global_config.system.port} 测试")
    
    uvicorn.run(
        'anima.socketio_server:socket_app',
        host=global_config.system.host,
        port=global_config.system.port,
        reload=True
    )