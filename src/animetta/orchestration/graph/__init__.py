"""
LangGraph node module

Implements each processing node, each node is responsible for:
1. Reading specific fields from the state
2. Calling existing services (implementations in services/)
3. Writing results back to the state

Node principles:
- Do not rewrite business logic, reuse all existing services
- Only responsible for state transitions and service calls
- Error handling: set state["error"] on failure
"""

from .asr_node import asr_node
from .delivery_nodes import conversation_start_node, performance_output_node, reply_output_node
from .dialogue_nodes import (
    anima_composer_node,
    conversation_finalizer_node,
    reasoner_node,
    response_guard_node,
)
from .emotion_node import emotion_node
from .humor_rewrite_node import humor_rewrite_node
from .humor_validation_node import humor_validation_node
from .llm_node import llm_node
from .output_node import output_node
from .tool_node import tool_node
from .tts_node import tts_node

__all__ = [
    "asr_node",
    "llm_node",
    "humor_rewrite_node",
    "humor_validation_node",
    "tts_node",
    "emotion_node",
    "output_node",
    "tool_node",
    "reasoner_node",
    "anima_composer_node",
    "response_guard_node",
    "conversation_finalizer_node",
    "conversation_start_node",
    "reply_output_node",
    "performance_output_node",
]
