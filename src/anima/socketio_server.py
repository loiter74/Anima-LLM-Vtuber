"""
Socket.IO 服务端实现
基于 python-socketio 库，使用 ServiceContext 管理服务
参考 Open-LLM-VTuber 的实时对话逻辑

重构：使用 ConversationOrchestrator 整合对话逻辑
"""

import socketio
import json
import numpy as np
from fastapi import FastAPI
import uvicorn
from loguru import logger
from typing import Dict, Union, Optional

from anima.config import AppConfig
from anima.service_context import ServiceContext
from anima.services.conversation import (
    ConversationOrchestrator,
    SessionManager,
)
from anima.handlers import TextHandler
from anima.eventbus import EventPriority

# 创建 Socket.IO 服务器
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
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

# 全局配置（可被所有会话共享）
global_config: AppConfig = None


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
        config = global_config or AppConfig.load()
        await ctx.load_from_config(config)
        
        session_contexts[sid] = ctx
        logger.info(f"为会话 {sid} 创建了新的 ServiceContext")
    
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
            agent=ctx.agent_engine,
            websocket_send=websocket_send,
            session_id=sid,
        )
        
        # 创建并注册 TextHandler（使用 EventRouter）
        text_handler = TextHandler(websocket_send=websocket_send)
        orchestrator.register_handler("sentence", text_handler, priority=EventPriority.NORMAL)
        
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


# ============================================
# 连接事件处理
# ============================================

@sio.event
async def connect(sid, environ):
    """
    客户端连接时触发
    """
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
        return
    
    try:
        ctx = await get_or_create_context(sid)
        
        # 检查是否有 VAD 引擎
        if ctx.vad_engine is None:
            # 没有 VAD，直接累积音频
            audio_buffer_manager.append(sid, audio_chunk)
            return
        
        # 使用 VAD 检测语音
        for audio_bytes in ctx.vad_engine.detect_speech(audio_chunk):
            if audio_bytes == b"<|PAUSE|>":
                # 检测到暂停，发送打断信号
                await sio.emit('control', {
                    'type': 'control',
                    'text': 'interrupt'
                }, to=sid)
                
            elif audio_bytes == b"<|RESUME|>":
                # 恢复信号，继续
                pass
                
            elif len(audio_bytes) > 1024:
                # 检测到语音活动，保存音频并触发对话
                audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                audio_buffer_manager.append(sid, audio_data.tolist())
                
                # 触发对话（类似 mic_audio_end）
                await sio.emit('control', {
                    'type': 'control',
                    'text': 'mic-audio-end'
                }, to=sid)
                
    except Exception as e:
        logger.error(f"[{sid}] VAD 处理出错: {e}")


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
    
    # 打断编排器
    if sid in orchestrators:
        orchestrator = orchestrators[sid]
        await orchestrator.interrupt()
    
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
    if ctx.agent_engine:
        ctx.agent_engine.clear_history()
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