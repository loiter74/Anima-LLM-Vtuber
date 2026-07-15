from __future__ import annotations

"""Shared text processing utilities for bilibili danmaku and comment analysis.

Consolidates duplicate constants and functions previously scattered across
meme/bilibili_collector.py and meme/danmaku_buffer.py.
"""

import re

# ── Constants ────────────────────────────────────────────────────────────

STOPWORDS: frozenset[str] = frozenset(
    {
        "的",
        "了",
        "在",
        "是",
        "我",
        "有",
        "和",
        "就",
        "不",
        "人",
        "都",
        "一",
        "一个",
        "这个",
        "那个",
        "什么",
        "怎么",
        "如何",
        "可以",
        "没有",
        "还是",
        "但是",
        "因为",
        "所以",
        "如果",
        "虽然",
        "而且",
        "或者",
        "不是",
        "就是",
        "我们",
        "你们",
        "他们",
        "它们",
        "自己",
        "起来",
        "这些",
        "那些",
    }
)

TITLE_SEPARATORS: re.Pattern = re.compile(
    r"[,，、。！？：；" "''（）!?:\\;\"'\\(\\)\\s]|·|●|◆|【|】|《|》|—+"
)


# ── Public Functions ─────────────────────────────────────────────────────


def parse_tags(tag_str: str) -> list[str]:
    """Parse comma-separated tag string into cleaned individual tags.

    Args:
        tag_str: Raw comma-separated tag string from bilibili API.

    Returns:
        List of trimmed, non-empty tag strings.
    """
    if not tag_str:
        return []
    return [t.strip() for t in tag_str.split(",") if t.strip()]


def extract_title_phrases(title: str) -> list[str]:
    """Split a video title into candidate phrases using punctuation and length heuristics.

    Used by MemeCollector's heuristic meme identification (Strategy 2).

    Args:
        title: Raw video title string.

    Returns:
        List of candidate phrases (2-15 chars, non-numeric).
    """
    if not title:
        return []

    parts = TITLE_SEPARATORS.split(title)
    phrases: list[str] = []

    for part in parts:
        part = part.strip()
        # Keep 2-15 char segments that aren't pure numbers
        if 2 <= len(part) <= 15 and not part.isdigit():
            phrases.append(part)
            # Also extract 2-char sub-phrases for longer segments
            if len(part) > 4:
                for i in range(len(part) - 1):
                    sub = part[i : i + 2]
                    if sub not in STOPWORDS:
                        phrases.append(sub)

    return phrases
