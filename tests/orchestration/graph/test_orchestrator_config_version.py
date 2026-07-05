from __future__ import annotations

from unittest.mock import MagicMock

from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator


def test_initial_state_includes_runtime_config_version():
    ctx = MagicMock()
    ctx.session_id = "sid"
    ctx.runtime_config_version = 6
    orchestrator = LangGraphOrchestrator(service_context=ctx, socketio=None)
    orchestrator._get_persona_dict = MagicMock(return_value={})
    orchestrator._get_system_prompt = MagicMock(return_value="Base.")

    state = orchestrator._create_initial_state(input_type="text", user_text="hi")

    assert state["config_version"] == 6
    assert state["metadata"]["config_version"] == 6
