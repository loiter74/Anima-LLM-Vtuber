"""
记忆系统协调器

统一管理四层存储：短期、长期、向量搜索、知识图谱
"""

from typing import List, Optional, Dict
from loguru import logger
from .memory_turn import MemoryTurn
from .short_term import ShortTermMemory
from .long_term import LongTermMemory
from .importance_scorer import ImportanceScorer
from .vector_store import VectorStore


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
                - enable_vector_search: 是否启用向量搜索
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

        # 4. 向量存储（可选）
        self.vector_store = None
        if config.get("enable_vector_search", False):
            try:
                vector_path = config.get("vector_storage_path", "E:/AnimaData/vector_db")
                embedding_model = config.get("embedding_model", "paraphrase-multilingual-MiniLM-L12-v2")

                self.vector_store = VectorStore(
                    storage_path=vector_path,
                    embedding_model=embedding_model
                )
                logger.info("[MemorySystem] 向量搜索已启用")
            except Exception as e:
                logger.warning(f"[MemorySystem] 向量存储初始化失败: {e}")
                self.vector_store = None
        else:
            logger.info("[MemorySystem] 向量搜索未启用")

    async def store_turn(self, turn: MemoryTurn) -> None:
        """
        存储对话轮次

        流程：
        1. 评估重要性
        2. 存储到短期记忆
        3. 高重要性 → 长期记忆
        4. 存储到向量搜索（如果启用）

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

        # 4. 存储到向量搜索（第二层个性化）
        if self.vector_store:
            try:
                self.vector_store.add_conversation(
                    session_id=turn.session_id,
                    user_input=turn.user_input,
                    ai_response=turn.agent_response,
                    emotions=turn.emotions,
                    metadata={
                        "importance": turn.importance,
                        "timestamp": turn.timestamp.isoformat()
                    }
                )
            except Exception as e:
                logger.warning(f"[MemorySystem] 向量存储失败: {e}")

    async def retrieve_context(
        self,
        query: str,
        session_id: str,
        max_turns: int = 5
    ) -> List[MemoryTurn]:
        """
        检索相关记忆（增强版：向量搜索 + 关键词搜索）

        策略：多路召回
        1. 短期记忆：最近 N 轮
        2. 向量搜索：语义相关对话（如果启用）
        3. 长期记忆：全文搜索（FTS）

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
            session_id=session_id,
            n=max_turns
        )
        results.extend(recent)

        # 2. 向量搜索：语义相关（第二层个性化）
        if self.vector_store:
            try:
                vector_results = self.vector_store.search_relevant_context(
                    query=query,
                    session_id=session_id,
                    n_results=3
                )

                # 将向量搜索结果转换为MemoryTurn
                for vr in vector_results:
                    # 从文本中解析用户输入和AI回复
                    text = vr["text"]
                    lines = text.split("\n")
                    user_input = ""
                    agent_response = ""

                    for i, line in enumerate(lines):
                        if line.startswith("User: "):
                            user_input = line[6:]
                        elif line.startswith("AI: "):
                            agent_response = line[4:]

                    if user_input and agent_response:
                        from datetime import datetime
                        import uuid

                        memory_turn = MemoryTurn(
                            turn_id=str(uuid.uuid4()),
                            session_id=session_id,
                            timestamp=datetime.fromisoformat(vr["metadata"].get("timestamp", datetime.now().isoformat())),
                            user_input=user_input,
                            agent_response=agent_response,
                            emotions=vr["metadata"].get("emotions", "").split(",") if vr["metadata"].get("emotions") else [],
                            metadata=vr["metadata"],
                            importance=vr["metadata"].get("importance", 0.5)
                        )
                        results.append(memory_turn)

                logger.debug(f"[MemorySystem] 向量搜索返回 {len(vector_results)} 条结果")
            except Exception as e:
                logger.warning(f"[MemorySystem] 向量搜索失败: {e}")

        # 3. 长期记忆：全文搜索（FTS）
        try:
            relevant = await self.long_term.search(
                query=query,
                top_k=3,
                session_id=None  # 全局搜索
            )
            results.extend(relevant)
        except Exception as e:
            logger.warning(f"[MemorySystem] 长期记忆搜索失败: {e}")

        # 4. 去重（按 turn_id）
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
