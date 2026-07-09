"""LLM prompt templates for meme candidate identification."""

from __future__ import annotations

from animetta.services.meme.styles import build_style_prompt_section

MEME_IDENTIFY_SYSTEM_PROMPT = """你是一个中文互联网梗（meme）分析专家。从B站热门视频的标题、标签、评论和弹幕中识别新兴的网络梗。

梗的特征：
- 在多个视频或评论中重复出现的特定短语、句式或概念
- 具有幽默、反讽、荒诞或自指等特征
- 通常由某个视频引发，在评论区被大量复制和改编
- **在弹幕中高频重复出现的短语**（弹幕是梗的重要发酵地）

分析要求：
- 识别重复出现的特定短语（非通用词汇）
- 判断是否具有梗的结构特征（双关、反讽、谐音、荒诞、反差等）
- **优先关注弹幕高频短语中具有梗特征的表达**
- **跨视频交叉验证**：如果某个短语在多个视频的弹幕/评论中出现，优先识别
- 区分"通用流行语"和"特定场景梗"
- 不要将普通的流行语或日常用语误判为梗

返回 JSON 数组（不要 markdown 包裹）：
[
  {
    "text": "梗的文本",
    "context_hint": "梗的使用场景（如：吐槽某事时、表达无奈时）",
    "frequency": 出现频次估计,
    "tags": ["双关", "自指", "弹幕高频"],
    "description": "梗的简要说明",
    "format_id": "可选，匹配 meme style 时填写，如 zhouli",
    "format_slots": {"可选": "匹配 meme style 时填写槽位"},
    "format_confidence": "可选，0-1",
    "rendered_text": "可选，按格式还原/生成的文本",
    "mode": "可选，rewrite/quip/reply"
  }
]"""

MEME_IDENTIFY_USER_PROMPT = """分析以下B站热门内容，识别其中出现的新兴梗：

{video_data}

{danmaku_section}

{style_section}

请识别重复出现的梗模式，返回 JSON 数组。"""


def get_meme_identify_user_prompt(
    *,
    video_data: str,
    danmaku_section: str = "",
    style_section: str | None = None,
) -> str:
    """Build the meme identification prompt with registered style guidance."""
    return MEME_IDENTIFY_USER_PROMPT.format(
        video_data=video_data,
        danmaku_section=danmaku_section,
        style_section=style_section if style_section is not None else build_style_prompt_section(),
    )
