"""Assistant-flavor drift detector and one-turn correction for Anima v0.1.

Detects when LLM output starts sounding like a generic assistant
instead of staying in Anima's character voice.
"""

from __future__ import annotations

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

# One-turn correction content injected when drift is detected
CORRECTION_SECTION = """## 角色回归提醒
你的上一条回复出现了助手腔调。立即修正：
- 你是 Anima，赛博酒馆的召唤者 X，不是AI助手
- 禁止使用"作为AI"、"我理解你的意思"等助手式表达
- 用旅人们熟悉的语气对话，不要解释你在做什么"""


def detect_drift(text: str) -> list[str]:
    """Check if LLM output contains assistant-flavor phrases.

    Returns list of matched forbidden phrases (empty = no drift).
    """
    found = []
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            found.append(phrase)
    return found


def has_drift(text: str) -> bool:
    """Quick boolean check for drift."""
    return bool(detect_drift(text))
