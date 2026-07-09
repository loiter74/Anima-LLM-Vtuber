"""B站热梗情报服务 — 定期采集 B站热门视频、评论、弹幕，识别新兴梗模式.

MemeCognitiveAnalyzer (analyzer.py) remains local — it is platform-agnostic.
"""

from .styles import (
    DecoratedResponse,
    MemeInvocation,
    MemeRouteDecision,
    MemeRouter,
    MemeState,
    MemeStyle,
    MemeStyleExample,
    MemeStyleResult,
    MemeStyleSlot,
    MemeStyleValidationError,
    ZhouliTool,
    build_style_prompt_section,
    decorate_response,
    get_builtin_meme_styles,
    get_meme_style,
    parse_meme_invocation,
)

__all__ = [
    "DecoratedResponse",
    "MemeInvocation",
    "MemeRouter",
    "MemeRouteDecision",
    "MemeState",
    "MemeStyle",
    "MemeStyleExample",
    "MemeStyleResult",
    "MemeStyleSlot",
    "MemeStyleValidationError",
    "ZhouliTool",
    "build_style_prompt_section",
    "decorate_response",
    "get_builtin_meme_styles",
    "get_meme_style",
    "parse_meme_invocation",
]
