"""
会话管理器
管理多会话的 ConversationOrchestrator 实例
"""

from typing import Dict, Optional, Callable, Any
from loguru import logger

from .orchestrator import ConversationOrchestrator


class SessionManager:
    """
    会话管理器
    
    管理多个会话的 ConversationOrchestrator 实例
    支持会话的创建、获取、清理
    
    使用示例:
        session_manager = SessionManager()
        
        # 创建编排器工厂函数
        async def create_orchestrator(sid: str):
            orchestrator = ConversationOrchestrator(
                asr_engine=asr,
                tts_engine=tts,
                agent=agent,
                session_id=sid,
            )
            orchestrator.register_handler("sentence", text_handler)
            orchestrator.start()
            return orchestrator
        
        session_manager.set_factory(create_orchestrator)
        
        # 获取或创建会话
        orchestrator = await session_manager.get_or_create("session-001")
        
        # 清理会话
        await session_manager.cleanup("session-001")
    """
    
    def __init__(self):
        """初始化会话管理器"""
        self._sessions: Dict[str, ConversationOrchestrator] = {}
        self._factory: Optional[Callable] = None
    
    def set_factory(self, factory: Callable[[str], Any]) -> None:
        """
        设置编排器工厂函数
        
        Args:
            factory: 异步工厂函数，接受 session_id 参数
        """
        self._factory = factory
    
    async def get_or_create(self, session_id: str) -> ConversationOrchestrator:
        """
        获取或创建会话编排器
        
        Args:
            session_id: 会话 ID
            
        Returns:
            ConversationOrchestrator: 会话编排器
            
        Raises:
            RuntimeError: 如果未设置工厂函数
        """
        if session_id not in self._sessions:
            if self._factory is None:
                raise RuntimeError("未设置编排器工厂函数")
            
            logger.info(f"[SessionManager] 创建新会话: {session_id}")
            self._sessions[session_id] = await self._factory(session_id)
        
        return self._sessions[session_id]
    
    def get(self, session_id: str) -> Optional[ConversationOrchestrator]:
        """
        获取会话编排器（不创建）
        
        Args:
            session_id: 会话 ID
            
        Returns:
            ConversationOrchestrator 或 None
        """
        return self._sessions.get(session_id)
    
    async def cleanup(self, session_id: str) -> None:
        """
        清理会话
        
        Args:
            session_id: 会话 ID
        """
        if session_id in self._sessions:
            orchestrator = self._sessions[session_id]
            orchestrator.stop()
            del self._sessions[session_id]
            logger.info(f"[SessionManager] 已清理会话: {session_id}")
    
    async def cleanup_all(self) -> None:
        """清理所有会话"""
        for session_id in list(self._sessions.keys()):
            await self.cleanup(session_id)
        
        logger.info("[SessionManager] 已清理所有会话")
    
    def has_session(self, session_id: str) -> bool:
        """检查会话是否存在"""
        return session_id in self._sessions
    
    @property
    def session_count(self) -> int:
        """获取会话数量"""
        return len(self._sessions)
    
    def get_session_ids(self) -> list:
        """获取所有会话 ID"""
        return list(self._sessions.keys())