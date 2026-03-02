"""
记忆数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import numpy as np

@dataclass
class MemoryTurn:
    """
    单次对话数据

    Attributes:
        turn_id: 唯一标识符
        session_id: 会话 ID
        timestamp: 时间戳
        user_input: 用户输入
        agent_response: Agent 回复
        emotions: Live2D 表情列表
        metadata: 元数据
        importance: 重要性评分 (0-1)
        embedding: 向量嵌入（可选）
    """
    turn_id: str
    session_id: str
    timestamp: datetime
    user_input: str
    agent_response: str
    emotions: List[str]
    metadata: Dict[str, Any]
    importance: float = 0.5
    embedding: Optional[np.ndarray] = None


@dataclass
class Entity:
    """实体（知识图谱用）"""
    name: str
    type: str  # person, place, concept, etc.
    properties: Dict[str, Any]
    relations: List['Relation']


@dataclass
class Relation:
    """关系（知识图谱用）"""
    target: str
    type: str  # likes, knows, mentioned, etc.
    properties: Dict[str, Any]
