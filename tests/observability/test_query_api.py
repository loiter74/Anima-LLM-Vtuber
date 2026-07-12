from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from starlette.applications import Starlette
from starlette.testclient import TestClient

from animetta.observability.domain import ObservationHealth
from animetta.orchestration.server.stats_api import get_stats_routes


def _query() -> MagicMock:
    query = MagicMock()
    query.overview = AsyncMock(
        return_value={
            "schema_version": 2,
            "total_requests": 2,
            "success_count": 1,
            "degraded_count": 1,
            "failed_count": 0,
            "success_rate": 50.0,
            "avg_duration_ms": 125.0,
        }
    )
    query.operation_aggregates = AsyncMock(
        return_value=[
            {
                "layer": "workflow",
                "name": "llm_node",
                "provider": None,
                "model": None,
                "operation_count": 2,
                "success_count": 1,
                "degraded_count": 1,
                "failure_count": 0,
                "avg_duration_ms": 100.0,
            }
        ]
    )
    query.recent_traces = AsyncMock(
        return_value=[
            {
                "trace_id": "task-1",
                "message_id": "message-1",
                "conversation_id": "conversation-1",
                "session_id": "session-1",
                "runtime_profile": "golden",
                "input_type": "text",
                "privacy_mode": "redacted",
                "started_at": 10.0,
                "finished_at": 10.125,
                "duration_ms": 125.0,
                "outcome": "degraded",
                "error_type": None,
            }
        ]
    )
    operation = {
        "operation_id": "operation-1",
        "trace_id": "task-1",
        "parent_operation_id": None,
        "layer": "workflow",
        "name": "llm_node",
        "critical_path": True,
        "started_at": 10.0,
        "finished_at": 10.1,
        "duration_ms": 100.0,
        "status": "degraded",
        "provider": "openai",
        "model": "gpt-test",
        "error_type": None,
        "error_summary": None,
        "attributes": {},
    }
    event = {
        "event_id": "event-1",
        "trace_id": "task-1",
        "operation_id": "operation-1",
        "direction": "egress",
        "name": "chat:text",
        "phase": "delivered",
        "occurred_at": 10.1,
        "payload_size": 12,
        "identity_valid": True,
        "attributes": {},
    }
    query.trace_detail = AsyncMock(
        return_value={
            "trace_id": "task-1",
            "message_id": "message-1",
            "conversation_id": "conversation-1",
            "session_id": "session-1",
            "runtime_profile": "golden",
            "input_type": "text",
            "privacy_mode": "redacted",
            "started_at": 10.0,
            "finished_at": 10.125,
            "duration_ms": 125.0,
            "outcome": "degraded",
            "error_type": None,
            "error_summary": None,
            "user_text": None,
            "user_character_count": 6,
            "user_byte_count": 12,
            "user_digest": "user-digest",
            "assistant_text": None,
            "assistant_character_count": 4,
            "assistant_byte_count": 8,
            "assistant_digest": "assistant-digest",
            "attributes": {},
            "operations": [operation],
            "operation_tree": [{**operation, "children": []}],
            "events": [event],
            "post_turn": {
                "pending": 0,
                "completed": 1,
                "failed": 0,
                "operations": [{**operation, "critical_path": False}],
            },
            "schema_version": 2,
        }
    )
    query.trace_events = AsyncMock(return_value=[event])
    query.inspection_reports = AsyncMock(return_value=[])
    query.observation_health = AsyncMock(
        return_value=ObservationHealth(True, True, False)
    )
    return query


def _client(query: MagicMock) -> TestClient:
    app = Starlette(routes=get_stats_routes())
    app.state.observation_query = query
    return TestClient(app)


def test_stats_routes_use_injected_observation_query() -> None:
    query = _query()
    with _client(query) as client:
        overview = client.get("/api/stats/overview")
        nodes = client.get("/api/stats/nodes")
        traces = client.get("/api/stats/traces?limit=10&offset=2")

    assert overview.json()["api_version"] == "2"
    assert overview.json()["degraded_count"] == 1
    assert nodes.json()[0]["name"] == "llm_node"
    assert traces.json()[0]["outcome"] == "degraded"
    query.overview.assert_awaited_once()
    query.operation_aggregates.assert_awaited_once()
    query.recent_traces.assert_awaited_once_with(10, 2)


def test_trace_detail_exposes_real_tree_events_redaction_and_post_turn() -> None:
    query = _query()
    with _client(query) as client:
        response = client.get("/api/stats/traces/task-1/tree")

    assert response.status_code == 200
    detail = response.json()
    assert detail["outcome"] == "degraded"
    assert detail["operation_tree"][0]["name"] == "llm_node"
    assert detail["operation_tree"][0]["provider"] == "openai"
    assert detail["events"][0]["phase"] == "delivered"
    assert detail["content"]["user"]["text"] is None
    assert detail["content"]["user"]["digest"] == "user-digest"
    assert detail["post_turn"]["completed"] == 1


def test_events_and_health_are_versioned() -> None:
    query = _query()
    with _client(query) as client:
        events = client.get("/api/stats/traces/task-1/events")
        health = client.get("/api/stats/observation-health")

    assert events.json()["api_version"] == "2"
    assert events.json()["events"][0]["direction"] == "egress"
    assert health.json() == {
        "api_version": "2",
        "enabled": True,
        "ready": True,
        "degraded": False,
        "queue_depth": 0,
        "dropped_records": 0,
        "writer_errors": 0,
        "stale_traces_recovered": 0,
        "last_error": None,
    }


def test_stats_api_does_not_import_legacy_store_or_probe_private_db() -> None:
    source = (
        __import__("pathlib").Path("src/animetta/orchestration/server/stats_api.py")
        .read_text(encoding="utf-8")
    )
    assert "get_stats_store" not in source
    assert "._db" not in source
