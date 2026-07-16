from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.inspection.checks.pipeline import validate_observed_turn
from animetta.inspection.runtime import InspectionRuntime


def _operation(
    name: str,
    *,
    layer: str = "workflow",
    critical_path: bool = True,
) -> dict[str, object]:
    return {
        "name": name,
        "layer": layer,
        "critical_path": critical_path,
        "status": "success",
    }


def _runtime(
    task_id: str,
    workflow: tuple[str, ...],
    *,
    llm_calls: int,
) -> InspectionRuntime:
    query = MagicMock()
    query.trace_detail = AsyncMock(
        return_value={
            "trace_id": task_id,
            "outcome": "success",
            "operations": [
                *[_operation(name) for name in workflow],
                *[
                    {**_operation("llm.chat", layer="service"), "provider": "deepseek"}
                    for _ in range(llm_calls)
                ],
            ],
            "events": [
                {
                    "name": "chat:sentence",
                    "direction": "egress",
                    "phase": "delivered",
                }
            ],
        }
    )
    return InspectionRuntime(
        observation_query=query,
        report_store=MagicMock(),
        memory_runtime=MagicMock(),
        readiness_snapshot=lambda: {
            "components": {"tts": {"provider": "qwen3", "ready": True, "state": "ready"}}
        },
        metrics_snapshot=lambda: (
            'anima_trace_outcomes_total{outcome="success"} 2\n'
            'anima_node_duration_seconds_count{node_name="llm"} 14\n'
        ),
    )


@pytest.mark.parametrize(
    ("task_id", "workflow", "llm_calls"),
    [
        (
            "golden-task",
            (
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
            ),
            2,
        ),
        (
            "standard-task",
            (
                "personality",
                "llm",
                "humor_rewrite",
                "humor_validation",
                "tts",
                "emotion",
                "output",
            ),
            1,
        ),
        (
            "voice-task",
            (
                "asr",
                "personality",
                "llm",
                "humor_rewrite",
                "humor_validation",
                "tts",
                "emotion",
                "output",
            ),
            1,
        ),
    ],
)
async def test_observed_turn_matches_real_profile_topology(
    task_id: str,
    workflow: tuple[str, ...],
    llm_calls: int,
) -> None:
    runtime = _runtime(task_id, workflow, llm_calls=llm_calls)
    result = await validate_observed_turn(
        runtime,
        task_id=task_id,
        client_events=[("chat:sentence", {"task_id": task_id})],
        expected_workflow=workflow,
        expected_llm_calls=llm_calls,
        metrics_before=(
            'anima_trace_outcomes_total{outcome="success"} 1\n'
            'anima_node_duration_seconds_count{node_name="llm"} 7\n'
        ),
    )
    assert result.ok is True
    assert result.detail["metrics_delta"] == {
        "anima_trace_outcomes_total": 1.0,
        "anima_node_duration_seconds_count": 7.0,
    }


async def test_observed_turn_rejects_memory_write_and_missing_delivery_evidence() -> None:
    workflow = ("personality", "llm", "tts", "output")
    runtime = _runtime("task-1", workflow, llm_calls=1)
    detail = await runtime.observation_query.trace_detail("task-1")
    detail["operations"].append(_operation("memory.ingest", layer="memory", critical_path=False))
    detail["events"] = []

    result = await validate_observed_turn(
        runtime,
        task_id="task-1",
        client_events=[("chat:sentence", {})],
        expected_workflow=workflow,
        expected_llm_calls=1,
    )
    assert result.ok is False
    assert "prohibited_memory_write" in (result.error or "")
    assert "client_ledger_event_mismatch" in (result.error or "")


async def test_successful_real_tts_service_is_evidence_without_golden_readiness() -> None:
    workflow = (
        "personality",
        "llm",
        "humor_rewrite",
        "humor_validation",
        "tts",
        "emotion",
        "output",
    )
    runtime = _runtime("standard-task", workflow, llm_calls=1)
    detail = await runtime.observation_query.trace_detail("standard-task")
    detail["operations"].append(
        {
            **_operation("tts.synthesize", layer="service"),
            "provider": "mimo",
            "model": "mimo-v2.5-tts",
        }
    )
    runtime = InspectionRuntime(
        observation_query=runtime.observation_query,
        report_store=runtime.report_store,
        memory_runtime=runtime.memory_runtime,
        readiness_snapshot=lambda: {
            "profile": "development",
            "components": {"pool": {"ready": True}},
        },
        metrics_snapshot=runtime.metrics_snapshot,
    )

    result = await validate_observed_turn(
        runtime,
        task_id="standard-task",
        client_events=[("chat:sentence", {"task_id": "standard-task"})],
        expected_workflow=workflow,
        expected_llm_calls=1,
    )

    assert result.ok is True
    assert result.detail["tts_evidence"] is True
