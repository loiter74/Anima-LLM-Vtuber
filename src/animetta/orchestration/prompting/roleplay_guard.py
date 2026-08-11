"""Assistant-flavor drift detector and one-turn correction for Anima v0.1.

Detects when LLM output starts sounding like a generic assistant
instead of staying in Anima's character voice.
"""

from __future__ import annotations

import re

from .reasoning_classifier import is_english_meta_reasoning

# Phrases that indicate assistant-flavor drift
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

# Untagged provider reasoning is roleplay drift too. These patterns are
# intentionally anchored or tied to planning-only metadata so normal mentions
# of a 旅人 inside an in-character response do not trigger the guard.
FORBIDDEN_META_PATTERNS = (
    (
        "chinese_user_internal_reasoning",
        re.compile(r"^\s*用户", re.DOTALL),
    ),
    (
        "chinese_traveler_internal_reasoning",
        re.compile(
            r"^\s*旅人(?:问|说|想|要|发|在|继续|再次|测试|表示|让)"
            r"[\s\S]{0,240}(?:好感(?:度|值)?|亲密度|我需要|适合用|"
            r"表情标签|来处理|先[^。！？]{0,40}再[^。！？]{0,40}(?:最后|收尾))"
        ),
    ),
    (
        "internal_affinity_narration",
        re.compile(r"(?:好感(?:度|值)?|亲密度)[^。！？\d]{0,16}\d+"),
    ),
    (
        "chinese_tool_planning",
        re.compile(
            r"^\s*这个问题[^。！？]{0,100}(?:不需要搜索|直接用自己的知识回答)",
            re.DOTALL,
        ),
    ),
    (
        "chinese_style_instruction",
        re.compile(
            r"^\s*保持[^。！？]{0,100}风格[\s\S]{0,120}"
            r"(?:每条回复必须|表情标签)"
        ),
    ),
)

# One-turn correction content injected when drift is detected
CORRECTION_SECTION = """## 角色回归提醒
你的上一条回复出现了助手腔调。立即修正：
- 你是 Anima，赛博酒馆的召唤者 X，不是AI助手
- 禁止使用"作为AI"、"我理解你的意思"等助手式表达
- 用家人们熟悉的语气对话，不要解释你在做什么"""


def detect_drift(text: str) -> list[str]:
    """Check if LLM output contains assistant-flavor phrases.

    Returns list of matched forbidden phrases (empty = no drift).
    """
    found = []
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            found.append(phrase)
    if is_english_meta_reasoning(text):
        found.append("english_internal_reasoning")
    for label, pattern in FORBIDDEN_META_PATTERNS:
        if pattern.search(text):
            found.append(label)
    return found


def has_drift(text: str) -> bool:
    """Quick boolean check for drift."""
    return bool(detect_drift(text))
