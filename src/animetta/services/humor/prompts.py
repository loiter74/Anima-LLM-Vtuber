"""Prompt construction for Anima humor rewriting."""

from __future__ import annotations

import json
from typing import Any

from .config import HumorConfig
from .models import HumorRewriteRequest

_SYSTEM_PROMPT = """You are Anima's Humor Agent.
Rewrite an already-correct normal VTuber reply into a short Anima-style humorous reply.
Preserve the original intent and do not answer a different question.
Use only safe, affiliative or self-enhancing humor.
Avoid insults aimed at the viewer, hate, discrimination, sexual content, graphic violence, and customer-service phrasing.
Output exactly one JSON object and no markdown."""


def build_humor_messages(
    request: HumorRewriteRequest,
    config: HumorConfig,
) -> list[dict[str, str]]:
    """Build isolated messages for the internal rewrite call."""
    payload: dict[str, Any] = {
        "user_input": request.user_input,
        "normal_response": request.normal_response,
        "persona": request.persona or {},
        "metadata": request.metadata or {},
        "memory_context": request.memory_context,
        "worldview_hints": config.worldview_hints,
        "allowed_styles": config.allowed_styles,
        "candidate_count": config.candidate_count,
        "max_candidate_chars": config.max_candidate_chars,
        "required_schema": {
            "scene": "short situation label",
            "emotion": "viewer/user emotional tone",
            "humor_anchor": "what can be humorously twisted",
            "worldview_mapping": "how the anchor maps to Anima's configured motifs",
            "style": "affiliative or self-enhancing",
            "candidate_response": "final visible reply",
            "risk": "safe",
        },
    }
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, indent=2),
        },
    ]

