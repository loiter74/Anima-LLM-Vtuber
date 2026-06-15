"""LangGraph state graph builder"""

from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger

from . import asr_node, emotion_node, llm_node, output_node, tool_node, tts_node
from .personality_node import personality_node
from .state import AgentState

# Module-level external checkpointer — set by socketio_server at startup.
# When set, create_default_graph() uses this instead of constructing a new
# MemorySaver.  Enables Redis session sharing via --redis-url CLI flag.
_external_checkpointer: Any | None = None


def set_external_checkpointer(checkpointer: Any) -> None:
    """Set an external checkpointer for all graphs created by create_default_graph."""
    global _external_checkpointer
    _external_checkpointer = checkpointer
    logger.info(f"[LangGraph] External checkpointer registered: {type(checkpointer).__name__}")


def get_external_checkpointer() -> Any | None:
    """Get the current external checkpointer (or None)."""
    return _external_checkpointer


def route_input(state: AgentState) -> Literal["asr", "llm"]:
    """Determine the starting node based on input type"""
    input_type = state.get("input_type", "text")
    if input_type == "audio" and state.get("raw_audio"):
        logger.debug("[Router] Audio input -> ASR node")
        return "asr"
    logger.debug("[Router] Text input -> LLM node")
    return "llm"


def should_use_tools(state: AgentState) -> Literal["tools", "tts"]:
    """Check if LLM requested tool calls"""
    tool_calls = state.get("tool_calls")
    if tool_calls:
        logger.debug("[Router] LLM requested tool calls -> Tool node")
        return "tools"
    logger.debug("[Router] LLM direct reply -> TTS node")
    return "tts"


def build_graph(
    checkpointer: Any | None = None,
    enable_tools: bool = False,
    tools: list[Any] | None = None,
    tools_map: dict[str, Any] | None = None,
) -> StateGraph:
    """
    Build the LangGraph state graph

    Graph structure:
        [START]
           |
           +--(audio input)--> [asr_node]
           |                      |
           +--(text input)--------+-> [personality_node]
                                        |
                                   [llm_node]
                                        |
                               +--------+--------+
                               |                 |
                         (tool call)    (direct reply)
                               |                 |
                           [tool_node]        [tts_node]
                               |                 |
                               +-------+---------+
                                       |
                                  [tts_node]
                                       |
                                  [emotion_node]
                                       |
                                  [output_node]
                                       |
                                     [END]
    """
    logger.info("[LangGraph] Building state graph...")

    if enable_tools:
        logger.info(f"[LangGraph] Tool calls enabled, loading {len(tools or [])} tools")

    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("asr", asr_node)
    graph.add_node("personality", personality_node)
    graph.add_node("llm", llm_node)
    graph.add_node("tts", tts_node)
    graph.add_node("emotion", emotion_node)
    graph.add_node("output", output_node)

    registered_nodes = ["asr", "personality", "llm", "tts", "emotion", "output"]
    if enable_tools:
        graph.add_node("tools", tool_node)
        registered_nodes.append("tools")
        logger.info("[LangGraph] Tool node registered")

    logger.info(f"[LangGraph] Registered nodes: {registered_nodes}")

    # Set entry point
    graph.set_conditional_entry_point(route_input, {"asr": "asr", "llm": "personality"})

    # Add edges
    graph.add_edge("asr", "personality")
    graph.add_edge("personality", "llm")

    if enable_tools:
        graph.add_conditional_edges("llm", should_use_tools, {"tools": "tools", "tts": "tts"})
        graph.add_edge("tools", "llm")
        logger.info("[LangGraph] Tool loop configured: llm -> tools -> llm")
    else:
        graph.add_edge("llm", "tts")

    graph.add_edge("tts", "emotion")
    graph.add_edge("emotion", "output")
    graph.add_edge("output", END)

    logger.info("[LangGraph] State graph built")

    compiled_graph = graph.compile(checkpointer=checkpointer)
    logger.info("[LangGraph] State graph compiled")
    return compiled_graph


def create_default_graph(
    enable_memory: bool = True,
    enable_tools: bool = False,
    tools: list[Any] | None = None,
    tools_map: dict[str, Any] | None = None,
) -> StateGraph:
    """
    Create a state graph with default configuration

    Args:
        enable_memory: Whether to enable memory checkpoints
        enable_tools: Whether to enable tool calls
        tools: List of tools
        tools_map: Tool mapping

    Checkpointer priority:
    1. External checkpointer (set via set_external_checkpointer()) — used
       regardless of enable_memory flag.  This allows --redis-url to inject
       a Redis checkpointer.
    2. MemorySaver — when enable_memory=True and no external checkpointer.
    3. None — when enable_memory=False and no external checkpointer.
    """
    checkpointer = None

    if _external_checkpointer is not None:
        checkpointer = _external_checkpointer
        logger.info(f"[LangGraph] Using external checkpointer: {type(checkpointer).__name__}")
    elif enable_memory:
        checkpointer = MemorySaver()
        logger.info("[LangGraph] Memory checkpoint enabled")

    if enable_tools and not tools:
        logger.warning("[LangGraph] Tools enabled but no tool list provided, tool node will not work")

    return build_graph(
        checkpointer=checkpointer,
        enable_tools=enable_tools,
        tools=tools,
        tools_map=tools_map,
    )


def visualize_graph(graph: StateGraph, output_path: str = "graph.png") -> None:
    """Visualize the state graph (requires graphviz)"""
    try:
        img_data = graph.get_graph().draw_mermaid_png()

        with open(output_path, "wb") as f:
            f.write(img_data)

        logger.info(f"[LangGraph] Graph saved to: {output_path}")

    except ImportError:
        logger.warning("[LangGraph] Cannot visualize: missing graphviz or IPython")
    except Exception as e:
        logger.error(f"[LangGraph] Visualization failed: {e}")


def print_graph_structure(graph: StateGraph) -> None:
    """Print graph structure (for debugging)"""
    logger.info("[LangGraph] Graph structure:")
    logger.info(str(graph.get_graph().print_ascii()))
