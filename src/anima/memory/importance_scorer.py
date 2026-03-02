"""
重要性评分器

评估对话轮次的重要性，决定是否存储到长期记忆
"""

import re
from typing import List
from .memory_turn import MemoryTurn


class ImportanceScorer:
    """
    重要性评分器

    策略：
    1. 长度（长对话更重要）
    2. 情感强度（极端情绪更重要）
    3. 问题类型（提问 vs 闲聊）
    4. 关键词检测（"记住"、"喜欢"等）

    Returns:
        重要性分数 (0-1)
    """

    # 关键词列表
    IMPORTANT_KEYWORDS = [
        "记住", "重要", "喜欢", "讨厌", "总是",
        "从来", "一定要", "必须", "不要"
    ]

    # 提问词
    QUESTION_MARKS = ["?", "？", "什么", "如何", "怎么", "为什么"]

    def __init__(self, base_score: float = 0.5):
        """
        初始化评分器

        Args:
            base_score: 基础分数
        """
        self.base_score = base_score

    async def score(self, turn: MemoryTurn) -> float:
        """
        计算重要性分数

        Args:
            turn: 对话轮次

        Returns:
            重要性分数 (0-1)
        """
        score = self.base_score

        # 1. 长度加分（长对话更重要）
        total_length = len(turn.user_input) + len(turn.agent_response)
        if total_length > 200:
            score += 0.1
        if total_length > 500:
            score += 0.1

        # 2. 情感强度（极端情绪更重要）
        if "happy" in turn.emotions or "sad" in turn.emotions:
            score += 0.15

        # 3. 提问检测（用户在询问）
        if any(q in turn.user_input for q in self.QUESTION_MARKS):
            score += 0.15

        # 4. 关键词检测（用户明确表示重要性）
        for keyword in self.IMPORTANT_KEYWORDS:
            if keyword in turn.user_input:
                score += 0.15
                break  # 只加一次

        # 5. 限制在 [0, 1]
        return max(0.0, min(score, 1.0))
