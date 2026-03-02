"""
短期记忆（会话级）

快速访问的会话内存，容量有限（默认 20 轮对话）
"""

from typing import List, Dict
from collections import deque
from .memory_turn import MemoryTurn


class ShortTermMemory:
    """
    短期记忆（工作记忆）

    特点：
    - 快速访问（内存）
    - 容量有限（默认 20 轮对话）
    - 会话隔离
    - 自动丢弃旧数据

    Example:
        >>> memory = ShortTermMemory(max_turns=20)
        >>> turn = MemoryTurn(...)
        >>> await memory.add(turn)
        >>> recent = await memory.get_recent(n=5, session_id="session_123")
    """

    def __init__(self, max_turns: int = 20):
        """
        初始化短期记忆

        Args:
            max_turns: 最大保存轮数
        """
        self.max_turns = max_turns
        # 每个 session 一个 deque
        self.sessions: Dict[str, deque] = {}

    async def add(self, turn: MemoryTurn) -> None:
        """
        添加对话轮次

        Args:
            turn: 对话轮次数据
        """
        session_id = turn.session_id

        if session_id not in self.sessions:
            self.sessions[session_id] = deque(maxlen=self.max_turns)

        self.sessions[session_id].append(turn)

    async def get_recent(
        self,
        session_id: str,
        n: int = 5
    ) -> List[MemoryTurn]:
        """
        获取最近 N 轮对话

        Args:
            session_id: 会话 ID
            n: 获取数量

        Returns:
            最近 N 轮对话列表（按时间顺序）
        """
        if session_id not in self.sessions:
            return []

        session_deque = self.sessions[session_id]
        return list(session_deque)[-n:]

    async def get_all(self, session_id: str) -> List[MemoryTurn]:
        """
        获取所有短期记忆

        Args:
            session_id: 会话 ID

        Returns:
            该会话的所有对话
        """
        if session_id not in self.sessions:
            return []

        return list(self.sessions[session_id])

    async def clear(self, session_id: str) -> None:
        """
        清除会话记忆

        Args:
            session_id: 会话 ID
        """
        if session_id in self.sessions:
            del self.sessions[session_id]

    async def count(self, session_id: str) -> int:
        """
        获取会话对话轮数

        Args:
            session_id: 会话 ID

        Returns:
            对话轮数
        """
        if session_id not in self.sessions:
            return 0

        return len(self.sessions[session_id])
