"""Detect assistant-flavor drift and expose the one-turn correction prompt."""

from __future__ import annotations

import re

from .reasoning_classifier import is_english_meta_reasoning

FORBIDDEN_PHRASES = [
    "作为 AI",
    "作为一个AI",
    "作为人工智能",
    "我理解你的意思",
    "你可能是在表达",
    "以下是几点建议",
    "总结一下",
    "希望这能帮助你",
    "如果你有任何问题",
    "请随时告诉我",
    "很高兴为您服务",
    "作为助手",
]

FORBIDDEN_META_PATTERNS = (
    ("chinese_user_internal_reasoning", re.compile(r"^\s*用户", re.DOTALL)),
    (
        "chinese_traveler_internal_reasoning",
        re.compile(
            r"^\s*旅人(?:问|说|想|要|发|在|继续|再次|测试|表示|让)"
            r"[\s\S]{0,240}(?:好感(?:度|值)?|亲密度|我需要|适合用|"
            r"表情标签|来处理|先[^。！？]{0,40}再[^。！？]{0,40}(?:最后|收尾))"
        ),
    ),
    ("internal_affinity_narration", re.compile(r"(?:好感(?:度|值)?|亲密度)[^。！？\d]{0,16}\d+")),
    (
        "chinese_tool_planning",
        re.compile(
            r"^\s*这个问题[^。！？]{0,100}(?:不需要搜索|直接用自己的知识回答)",
            re.DOTALL,
        ),
    ),
    (
        "chinese_style_instruction",
        re.compile(r"^\s*保持[^。！？]{0,100}风格[\s\S]{0,120}(?:每条回复必须|表情标签)"),
    ),
)

CORRECTION_SECTION = """## 角色回归提醒
你的上一条回复出现了助手腔调。立即修正：
- 你是 Anima，赛博酒馆的召唤者 X，不是AI助手
- 禁止使用"作为AI"、"我理解你的意思"等助手式表达
- 用家人们熟悉的语气对话，不要解释你在做什么"""


def detect_drift(text: str) -> list[str]:
    """Return each phrase or reasoning pattern that indicates roleplay drift."""
    found = [phrase for phrase in FORBIDDEN_PHRASES if phrase in text]
    if is_english_meta_reasoning(text):
        found.append("english_internal_reasoning")
    found.extend(label for label, pattern in FORBIDDEN_META_PATTERNS if pattern.search(text))
    return found


def has_drift(text: str) -> bool:
    """Return whether the output drifted from the configured character voice."""
    return bool(detect_drift(text))


__all__ = [
    "CORRECTION_SECTION",
    "FORBIDDEN_META_PATTERNS",
    "FORBIDDEN_PHRASES",
    "detect_drift",
    "has_drift",
]
