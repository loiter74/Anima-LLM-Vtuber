"""
长期记忆（持久化存储）

跨会话保存对话历史，支持语义搜索
"""

import sqlite3
import json
from typing import List, Optional
from datetime import datetime
from .memory_turn import MemoryTurn


class LongTermMemory:
    """
    长期记忆（持久化存储）

    特点：
    - 跨会话保存
    - 全文搜索（FTS）
    - 向量嵌入（可选，暂不实现）

    Example:
        >>> memory = LongTermMemory(db_path="memory_db/memories.db")
        >>> turn = MemoryTurn(...)
        >>> await memory.store(turn)
        >>> results = await memory.search("你好", top_k=3)
    """

    def __init__(self, db_path: str = "memory_db/memories.db"):
        """
        初始化长期记忆

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_database()

    def _init_database(self) -> None:
        """初始化数据库表"""
        # 创建主表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_input TEXT NOT NULL,
                agent_response TEXT NOT NULL,
                emotions TEXT,
                metadata TEXT,
                importance REAL DEFAULT 0.5
            )
        """)

        # 创建索引
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_timestamp "
            "ON memories(session_id, timestamp DESC)"
        )

        # 创建全文搜索虚拟表（用于语义搜索）
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(user_input, agent_response, content=memories, content_rowid=id)
        """)

        self.conn.commit()

    async def store(self, turn: MemoryTurn) -> None:
        """
        存储到长期记忆

        Args:
            turn: 对话轮次数据
        """
        self.conn.execute(
            """
            INSERT INTO memories
            (turn_id, session_id, timestamp, user_input, agent_response,
             emotions, metadata, importance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn.turn_id,
                turn.session_id,
                turn.timestamp.isoformat(),
                turn.user_input,
                turn.agent_response,
                json.dumps(turn.emotions),
                json.dumps(turn.metadata),
                turn.importance
            )
        )

        self.conn.commit()

    async def search(
        self,
        query: str,
        top_k: int = 3,
        session_id: Optional[str] = None
    ) -> List[MemoryTurn]:
        """
        搜索相关记忆

        策略：使用全文搜索（FTS）

        Args:
            query: 搜索关键词
            top_k: 返回结果数量
            session_id: 可选，限制在特定会话

        Returns:
            相关记忆列表
        """
        if session_id:
            # 在特定会话中搜索
            results = self.conn.execute(
                """
                SELECT * FROM memories
                WHERE session_id = ?
                  AND memories_fts MATCH ?
                ORDER BY importance DESC, timestamp DESC
                LIMIT ?
                """,
                (session_id, query, top_k)
            ).fetchall()
        else:
            # 全局搜索
            results = self.conn.execute(
                """
                SELECT * FROM memories
                WHERE memories_fts MATCH ?
                ORDER BY importance DESC, timestamp DESC
                LIMIT ?
                """,
                (query, top_k)
            ).fetchall()

        return [self._row_to_turn(row) for row in results]

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
        results = self.conn.execute(
            """
            SELECT * FROM memories
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (session_id, limit)
        ).fetchall()

        return [self._row_to_turn(row) for row in results]

    def _row_to_turn(self, row) -> MemoryTurn:
        """数据库行 → MemoryTurn"""
        return MemoryTurn(
            turn_id=str(row[1]),
            session_id=row[2],
            timestamp=datetime.fromisoformat(row[3]),
            user_input=row[4],
            agent_response=row[5],
            emotions=json.loads(row[6]),
            metadata=json.loads(row[7]),
            importance=row[8],
            embedding=None  # 暂不使用向量嵌入
        )

    def close(self) -> None:
        """关闭数据库连接"""
        self.conn.close()
