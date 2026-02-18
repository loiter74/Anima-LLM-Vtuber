"""
Socket.IO 服务端实现
基于 python-socketio 库，使用 ServiceContext 管理服务
"""

import socketio
from fastapi import FastAPI
import uvicorn
from loguru import logger
from typing import Dict

from anima.config import AppConfig
from anima.service_context import ServiceContext

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

# 全局配置（可被所有会话共享）
global_config: AppConfig = None


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
        async def send_text_callback(event: str, data: dict):
            await sio.emit(event, data, to=sid)
        
        ctx.send_text = send_text_callback
        
        # 加载配置（使用全局配置或默认配置）
        config = global_config or AppConfig.load()
        await ctx.load_from_config(config)
        
        session_contexts[sid] = ctx
        logger.info(f"为会话 {sid} 创建了新的 ServiceContext")
    
    return session_contexts[sid]


async def cleanup_context(sid: str) -> None:
    """
    清理指定会话的 ServiceContext
    
    Args:
        sid: session id
    """
    if sid in session_contexts:
        ctx = session_contexts[sid]
        await ctx.close()
        del session_contexts[sid]
        logger.info(f"已清理会话 {sid} 的 ServiceContext")


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


@sio.event
async def disconnect(sid):
    """
    客户端断开时触发
    """
    logger.info(f"客户端已断开: {sid}")
    
    # 清理该会话的 ServiceContext
    await cleanup_context(sid)


# ============================================
# 业务事件处理
# ============================================

@sio.event
async def text_input(sid, data):
    """
    处理文本输入
    """
    text = data.get('text', '')
    logger.info(f"[{sid}] 收到文本输入: {text}")
    
    try:
        ctx = await get_or_create_context(sid)
        response = await ctx.process_text_input(text)
        
        # 发送回复
        await sio.emit('full-text', {
            'type': 'full-text',
            'text': response
        }, to=sid)
        
    except Exception as e:
        logger.error(f"[{sid}] 处理文本输入时出错: {e}")
        await sio.emit('full-text', {
            'type': 'full-text',
            'text': f'处理出错: {str(e)}'
        }, to=sid)


@sio.event
async def mic_audio_data(sid, data):
    """
    处理音频数据流
    """
    audio = data.get('audio', [])
    logger.debug(f"[{sid}] 收到音频数据: {len(audio)} 个采样点")
    
    # TODO: 将音频数据添加到缓冲区
    # 这里可以扩展为实时 VAD 处理


@sio.event
async def mic_audio_end(sid, data):
    """
    用户说完话，触发完整对话流程
    """
    logger.info(f"[{sid}] 音频输入结束")
    
    try:
        ctx = await get_or_create_context(sid)
        
        # TODO: 从缓冲区获取完整音频数据
        # audio_data = get_audio_buffer(sid)
        
        # 目前返回模拟响应
        await sio.emit('audio-path', {
            'type': 'audio-path',
            'text': '这是一个模拟的语音回复',
            'audio_url': '/cache/mock_audio.wav'
        }, to=sid)
        
    except Exception as e:
        logger.error(f"[{sid}] 处理音频时出错: {e}")
        await sio.emit('control', {
            'type': 'control',
            'text': 'error',
            'message': str(e)
        }, to=sid)


@sio.event
async def interrupt_signal(sid, data):
    """
    打断信号
    """
    logger.info(f"[{sid}] 收到打断信号")
    
    ctx = await get_or_create_context(sid)
    ctx.is_speaking = False
    
    await sio.emit('control', {
        'type': 'control',
        'text': 'stop-speaking'
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
async def switch_config(sid, data):
    """
    切换配置
    """
    config_name = data.get('file', 'default')
    logger.info(f"[{sid}] 切换配置: {config_name}")
    
    try:
        ctx = await get_or_create_context(sid)
        
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
