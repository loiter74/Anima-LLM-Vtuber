"""
记忆系统协调器

统一管理三层存储：短期、长期、知识图谱
"""

from typing import List, Optional, Dict
from .memory_turn import MemoryTurn
from .short_term import ShortTermMemory
from .long_term import LongTermMemory
from .importance_scorer import ImportanceScorer


class MemorySystem:
    """
    记忆系统统一入口

    职责：
    1. 协调三层存储
    2. 提供统一 API
    3. 智能路由（短期 vs 长期）
    4. 重要性评估

    Example:
        >>> memory = MemorySystem({
        ...     "short_term_max_turns": 20,
        ...     "long_term_db_path": "data/memories.db",
        ...     "importance_threshold": 0.7
        ... })
        >>> turn = MemoryTurn(...)
        >>> await memory.store_turn(turn)
        >>> results = await memory.retrieve_context(
        ...     query="你好",
        ...     session_id="session_123"
        ... )
    """

    def __init__(self, config: Dict):
        """
        初始化记忆系统

        Args:
            config: 配置字典
                - short_term_max_turns: 短期记忆容量
                - long_term_db_path: 长期记忆数据库路径
                - importance_threshold: 长期存储阈值
        """
        max_turns = config.get("short_term_max_turns", 20)

        # 1. 短期记忆
        self.short_term = ShortTermMemory(max_turns=max_turns)

        # 2. 长期记忆
        db_path = config.get("long_term_db_path", "data/memories.db")
        self.long_term = LongTermMemory(db_path=db_path)

        # 3. 重要性评分器
        self.importance_threshold = config.get("importance_threshold", 0.7)
        self.importance_scorer = ImportanceScorer()

    async def store_turn(self, turn: MemoryTurn) -> None:
        """
        存储对话轮次

        流程：
        1. 评估重要性
        2. 存储到短期记忆
        3. 高重要性 → 长期记忆

        Args:
            turn: 对话轮次数据
        """
        # 1. 评估重要性
        turn.importance = await self.importance_scorer.score(turn)

        # 2. 存储到短期记忆
        await self.short_term.add(turn)

        # 3. 高重要性 → 长期记忆
        if turn.importance >= self.importance_threshold:
            await self.long_term.store(turn)

    async def retrieve_context(
        self,
        query: str,
        session_id: str,
        max_turns: int = 5
    ) -> List[MemoryTurn]:
        """
        检索相关记忆

        策略：多路召回
        1. 短期记忆：最近 N 轮
        2. 长期记忆：语义搜索

        Args:
            query: 查询文本
            session_id: 会话 ID
            max_turns: 短期记忆返回数量

        Returns:
            相关记忆列表
        """
        results = []

        # 1. 短期记忆：最近 N 轮
        recent = await self.short_term.get_recent(
            n=max_turns,
            session_id=session_id
        )
        results.extend(recent)

        # 2. 长期记忆：语义搜索
        try:
            relevant = await self.long_term.search(
                query=query,
                top_k=3,
                session_id=None  # 全局搜索
            )
            results.extend(relevant)
        except Exception as e:
            # 长期记忆搜索失败，只返回短期记忆
            pass

        # 3. 去重（按 turn_id）
        seen = set()
        unique_results = []
        for turn in results:
            if turn.turn_id not in seen:
                seen.add(turn.turn_id)
                unique_results.append(turn)

        return unique_results

    async def get_user_history(
        self,
        session_id: str,
        limit: int = 50
    ) -> List[MemoryTurn]:
        """
        获取用户历史记录

        Args:
            session_id: 会话 ID
            limit: 返回记录数量

        Returns:
            历史对话列表（按时间倒序）
        """
        return await self.long_term.get_user_history(
            session_id=session_id,
            limit=limit
        )

    async def clear_session(self, session_id: str) -> None:
        """
        清除会话（短期记忆）

        Args:
            session_id: 会话 ID
        """
        await self.short_term.clear(session_id)

    def close(self) -> None:
        """关闭记忆系统"""
        self.long_term.close()
