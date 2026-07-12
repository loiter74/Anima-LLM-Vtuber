from __future__ import annotations

from animetta.orchestration.graph.state import AgentState

"""Tests for LangGraph state graph builder — node registration, routing, and compilation."""

from typing import Any
from unittest.mock import ANY, MagicMock, call, patch

import pytest
from langgraph.graph import StateGraph as RealStateGraph

import animetta.orchestration.graph.builder as builder_mod
from animetta.observability.ports import NoOpObservationRecorder
from animetta.orchestration.graph.builder import (
    build_graph,
    create_default_graph,
    get_external_checkpointer,
    print_graph_structure,
    route_input,
    set_external_checkpointer,
    should_use_tools,
    visualize_graph,
)
from animetta.orchestration.graph.state import create_initial_state

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_external_checkpointer():
    """Reset the module-level checkpointer before and after each test."""
    orig = builder_mod._external_checkpointer
    builder_mod._external_checkpointer = None
    yield
    builder_mod._external_checkpointer = orig


@pytest.fixture
def mock_state_graph():
    """Mock StateGraph with a compiled mock return."""
    graph = MagicMock(spec=RealStateGraph)
    compiled = MagicMock()
    graph.compile.return_value = compiled
    return graph, compiled


@pytest.fixture
def mock_tools():
    """Return a list of mock tool definitions."""
    return [MagicMock(name="tool1"), MagicMock(name="tool2")]


def _make_state(overrides: dict | None = None) -> dict[str, Any]:
    """Helper: build an AgentState dict from overrides."""
    base = dict(create_initial_state(session_id="test-session"))
    if overrides:
        base.update(overrides)
    return base


# ── Routing functions ───────────────────────────────────────


class TestRouteInput:
    """route_input() determines the starting node based on input type."""

    def test_audio_input_returns_asr(self):
        """Audio with raw_audio routes to 'asr'."""
        state = _make_state({"input_type": "audio", "raw_audio": b"fake"})
        assert route_input(state) == "asr"

    def test_audio_without_raw_audio_returns_llm(self):
        """Audio without raw_audio falls through to 'llm'."""
        state = _make_state({"input_type": "audio", "raw_audio": None})
        assert route_input(state) == "llm"

    def test_text_input_returns_llm(self):
        """Default text input routes to 'llm'."""
        state = _make_state({"input_type": "text"})
        assert route_input(state) == "llm"

    def test_empty_input_type_defaults_to_llm(self):
        """Missing input_type defaults safely to 'llm'."""
        state = _make_state({"input_type": ""})
        assert route_input(state) == "llm"


class TestShouldUseTools:
    """should_use_tools() decides between tools and humor rewrite."""

    def test_with_tool_calls_returns_tools(self):
        """When tool_calls is populated, route to 'tools'."""
        state = _make_state({"tool_calls": [{"name": "search"}]})
        assert should_use_tools(state) == "tools"

    def test_without_tool_calls_returns_tts(self):
        """When tool_calls is None, route to 'humor_rewrite'."""
        state = _make_state({"tool_calls": None})
        assert should_use_tools(state) == "humor_rewrite"

    def test_empty_tool_calls_returns_tts(self):
        """Empty list also routes to 'humor_rewrite'."""
        state = _make_state({"tool_calls": []})
        assert should_use_tools(state) == "humor_rewrite"


# ── External checkpointer ───────────────────────────────────


class TestExternalCheckpointer:
    """Module-level checkpointer set/get/reset."""

    def test_default_is_none(self):
        """Initially _external_checkpointer is None."""
        assert builder_mod._external_checkpointer is None

    def test_set_checkpointer(self):
        """set_external_checkpointer stores the checkpointer."""
        cp = MagicMock()
        set_external_checkpointer(cp)
        assert builder_mod._external_checkpointer is cp

    def test_get_checkpointer_returns_value(self):
        """get_external_checkpointer retrieves the stored value."""
        cp = MagicMock()
        set_external_checkpointer(cp)
        assert get_external_checkpointer() is cp

    def test_get_checkpointer_when_none(self):
        """get_external_checkpointer returns None when unset."""
        assert get_external_checkpointer() is None
        assert builder_mod._external_checkpointer is None

    def test_set_checkpointer_overwrites(self):
        """Setting a new checkpointer overwrites the old one."""
        cp1 = MagicMock()
        cp2 = MagicMock()
        set_external_checkpointer(cp1)
        set_external_checkpointer(cp2)
        assert builder_mod._external_checkpointer is cp2


# ── build_graph() ───────────────────────────────────────────


class TestBuildGraph:
    """build_graph() creates and compiles a StateGraph."""

    def test_build_graph_creates_state_graph(self, mock_state_graph):
        """StateGraph is instantiated with AgentState."""
        graph, compiled = mock_state_graph
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph) as mock_sg:
            result = build_graph()

        assert result is compiled
        mock_sg.assert_called_once()
        assert AgentState in mock_sg.call_args[0]
        graph.compile.assert_called_once_with(checkpointer=None)

    def test_build_graph_registers_core_nodes(self, mock_state_graph):
        """All core nodes are registered (tools disabled)."""
        graph, compiled = mock_state_graph
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph):
            build_graph()

        node_names = [c.args[0] for c in graph.add_node.call_args_list]
        assert node_names == [
            "asr",
            "personality",
            "llm",
            "humor_rewrite",
            "humor_validation",
            "tts",
            "emotion",
            "output",
        ]

    @pytest.mark.parametrize(
        ("golden_profile", "expected"),
        [
            (
                False,
                {
                    "asr",
                    "personality",
                    "llm",
                    "humor_rewrite",
                    "humor_validation",
                    "tts",
                    "emotion",
                    "output",
                },
            ),
            (
                True,
                {
                    "asr",
                    "conversation_start",
                    "personality",
                    "reasoner",
                    "anima_composer",
                    "response_guard",
                    "reply_output",
                    "tts",
                    "emotion",
                    "performance_output",
                    "conversation_finalizer",
                },
            ),
        ],
    )
    def test_every_registered_node_uses_exact_runtime_instrumentation_name(
        self, mock_state_graph, golden_profile, expected
    ):
        graph, _ = mock_state_graph
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph):
            build_graph(
                golden_profile=golden_profile,
                observation_recorder=NoOpObservationRecorder(),
            )

        registrations = {
            item.args[0]: getattr(item.args[1], "observation_node_name", None)
            for item in graph.add_node.call_args_list
        }
        assert set(registrations) == expected
        assert registrations == {name: name for name in expected}

    def test_build_graph_registers_tool_node(self, mock_state_graph, mock_tools):
        """When enable_tools=True, the 'tools' node is also registered."""
        graph, compiled = mock_state_graph
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph):
            build_graph(enable_tools=True, tools=mock_tools)

        node_names = [c.args[0] for c in graph.add_node.call_args_list]
        assert "tools" in node_names
        assert len(node_names) == 9

    def test_build_graph_sets_conditional_entry_point(self, mock_state_graph):
        """Entry point is set with route_input and asr/llm mapping."""
        graph, compiled = mock_state_graph
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph):
            build_graph()

        graph.set_conditional_entry_point.assert_called_once_with(
            route_input, {"asr": "asr", "llm": "personality"}
        )

    def test_build_graph_edges_without_tools(self, mock_state_graph):
        """Without tools: direct replies pass through humor nodes before TTS."""
        graph, compiled = mock_state_graph
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph):
            build_graph()

        edge_calls = graph.add_edge.call_args_list
        assert call("asr", "personality") in edge_calls
        assert call("personality", "llm") in edge_calls
        assert call("llm", "humor_rewrite") in edge_calls
        assert call("humor_rewrite", "humor_validation") in edge_calls
        assert call("humor_validation", "tts") in edge_calls
        assert call("llm", "tts") not in edge_calls
        assert call("tts", "emotion") in edge_calls
        assert call("emotion", "output") in edge_calls
        # END edge
        assert call("output", ANY) in edge_calls

    def test_build_graph_edges_with_tools(self, mock_state_graph, mock_tools):
        """With tools: conditional edges choose tools or humor rewrite, plus tools->llm loop."""
        graph, compiled = mock_state_graph
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph):
            build_graph(enable_tools=True, tools=mock_tools)

        # llm -> tts should NOT be a direct edge
        edge_calls = graph.add_edge.call_args_list
        assert call("llm", "tts") not in edge_calls
        # Instead, conditional edges and tools loop
        graph.add_conditional_edges.assert_called_once_with(
            "llm", should_use_tools, {"tools": "tools", "humor_rewrite": "humor_rewrite"}
        )
        assert call("tools", "llm") in edge_calls
        assert call("humor_rewrite", "humor_validation") in edge_calls
        assert call("humor_validation", "tts") in edge_calls

    def test_build_graph_passes_checkpointer(self, mock_state_graph):
        """Compile receives the supplied checkpointer."""
        graph, compiled = mock_state_graph
        cp = MagicMock()
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph):
            build_graph(checkpointer=cp)

        graph.compile.assert_called_once_with(checkpointer=cp)

    def test_build_graph_no_checkpointer(self, mock_state_graph):
        """Compile receives None when no checkpointer given."""
        graph, compiled = mock_state_graph
        with patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph):
            build_graph()

        graph.compile.assert_called_once_with(checkpointer=None)


# ── create_default_graph() ──────────────────────────────────


class TestCreateDefaultGraph:
    """create_default_graph() factory with checkpointer logic."""

    def test_no_memory_no_external(self, mock_state_graph):
        """enable_memory=False and no external cp → checkpointer=None."""
        graph, compiled = mock_state_graph
        with (
            patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph),
            patch("animetta.orchestration.graph.builder._external_checkpointer", None),
        ):
            create_default_graph(enable_memory=False)

        graph.compile.assert_called_once_with(checkpointer=None)

    def test_memory_saver_used(self, mock_state_graph):
        """enable_memory=True → MemorySaver instance is passed as checkpointer."""
        graph, compiled = mock_state_graph
        mock_memory = MagicMock()
        with (
            patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph),
            patch("animetta.orchestration.graph.builder._external_checkpointer", None),
            patch("animetta.orchestration.graph.builder.MemorySaver", return_value=mock_memory),
        ):
            create_default_graph(enable_memory=True)

        graph.compile.assert_called_once_with(checkpointer=mock_memory)

    def test_external_checkpointer_takes_priority(self, mock_state_graph):
        """External checkpointer wins over MemorySaver."""
        graph, compiled = mock_state_graph
        external_cp = MagicMock()
        with (
            patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph),
            patch("animetta.orchestration.graph.builder._external_checkpointer", external_cp),
        ):
            create_default_graph(enable_memory=True)

        graph.compile.assert_called_once_with(checkpointer=external_cp)

    def test_external_checkpointer_even_without_memory(self, mock_state_graph):
        """External checkpointer is used even when enable_memory=False."""
        graph, compiled = mock_state_graph
        external_cp = MagicMock()
        with (
            patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph),
            patch("animetta.orchestration.graph.builder._external_checkpointer", external_cp),
        ):
            create_default_graph(enable_memory=False)

        graph.compile.assert_called_once_with(checkpointer=external_cp)

    def test_tools_warning_no_tool_list(self, mock_state_graph):
        """enable_tools=True without tools list logs a warning."""
        graph, compiled = mock_state_graph
        with (
            patch("animetta.orchestration.graph.builder.StateGraph", return_value=graph),
            patch("animetta.orchestration.graph.builder.logger") as mock_logger,
        ):
            create_default_graph(enable_memory=False, enable_tools=True)

        mock_logger.warning.assert_called()
        warning_msg = str(mock_logger.warning.call_args)
        assert "no tool list provided" in warning_msg.lower()


# ── Utility functions ───────────────────────────────────────


class TestVisualizeGraph:
    """visualize_graph() edge cases."""

    def test_visualize_graph_missing_ipython(self, caplog):
        """When graphviz/IPython missing, a warning is logged."""
        mock_graph = MagicMock()
        mock_graph.get_graph.return_value.draw_mermaid_png.side_effect = ImportError("no graphviz")

        with patch("animetta.orchestration.graph.builder.logger") as mock_logger:
            visualize_graph(mock_graph, output_path="/dev/null/test.png")

        mock_logger.warning.assert_called()
        assert any("Missing graphviz" in str(c) or "IPython" in str(c) for c in mock_logger.warning.call_args)

    def test_visualize_graph_saves_file(self):
        """When successful, the PNG data is written to disk."""
        mock_graph = MagicMock()
        mock_graph.get_graph.return_value.draw_mermaid_png.return_value = b"pngdata"
        mock_file = MagicMock()

        with (
            patch.dict("sys.modules", {"IPython": MagicMock(), "IPython.display": MagicMock()}),
            patch("builtins.open", return_value=mock_file) as mock_open,
        ):
            visualize_graph(mock_graph, output_path="/tmp/test_graph.png")

        mock_open.assert_called_once_with("/tmp/test_graph.png", "wb")
        mock_file.__enter__.return_value.write.assert_called_once_with(b"pngdata")


class TestPrintGraphStructure:
    """print_graph_structure() output."""

    def test_print_graph_structure_calls_ascii(self):
        """print_graph_structure calls print_ascii and logs the result."""
        mock_graph = MagicMock()
        mock_graph.get_graph.return_value.print_ascii.return_value = "mock ascii art"

        with patch("animetta.orchestration.graph.builder.logger") as mock_logger:
            print_graph_structure(mock_graph)

        mock_graph.get_graph.assert_called_once()
        mock_logger.info.assert_any_call("mock ascii art")


def test_golden_graph_contains_only_two_pass_dialogue_branch() -> None:
    graph = build_graph(golden_profile=True)
    nodes = set(graph.get_graph().nodes)
    assert {"reasoner", "anima_composer", "response_guard", "conversation_finalizer"} <= nodes
    assert {"llm", "humor_rewrite", "humor_validation", "tools"}.isdisjoint(nodes)
