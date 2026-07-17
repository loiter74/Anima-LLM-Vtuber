"""Character-bounded instructions for the six supported response emotions."""

from __future__ import annotations

_CHARACTER_CONSTRAINT = "保持冷静、克制、有教养，不卖萌、不夸张。"
_EMOTION_MODIFIERS = {
    "neutral": "语气平稳，语速自然，音量适中。",
    "happy": "保留轻微愉悦，句尾轻微上扬，语速稍快。",
    "sad": "情绪低落但不使用哭腔，放慢语速，音量稍低，停顿略长。",
    "angry": "表达愤怒但不失态，压低声音，咬字坚定，语速略慢。",
    "surprised": "表达惊讶但不夸张，关键词前短暂停顿，语速短暂加快。",
    "thinking": "加入自然的思考停顿，语速稍慢，音量平稳，避免拖长。",
}


def build_emotion_instruction(emotion: str) -> str:
    """Return one stable character instruction, falling back to neutral."""

    modifier = _EMOTION_MODIFIERS.get(emotion, _EMOTION_MODIFIERS["neutral"])
    return f"{_CHARACTER_CONSTRAINT}{modifier}"


def all_emotion_instructions() -> tuple[str, ...]:
    """Return the stable instruction set used to prewarm the six hot sessions."""

    return tuple(build_emotion_instruction(emotion) for emotion in _EMOTION_MODIFIERS)
