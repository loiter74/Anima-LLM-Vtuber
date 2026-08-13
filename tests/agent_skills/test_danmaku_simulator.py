from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

SCRIPT = (
    Path(__file__).parents[2]
    / ".agents"
    / "skills"
    / "simulate-live-danmaku"
    / "scripts"
    / "danmaku_simulator.py"
)


def load_simulator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("danmaku_simulator", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scenarios_are_deterministic_monotonic_and_synthetic() -> None:
    simulator = load_simulator()
    synthetic_actors = {actor[0] for actor in simulator.ACTORS}

    for scenario in simulator.SCENARIO_DESCRIPTIONS:
        first = simulator.render_jsonl(scenario, 20260813)
        second = simulator.render_jsonl(scenario, 20260813)
        events = [json.loads(line) for line in first.splitlines()]

        assert first == second
        assert events
        assert [event["offset_ms"] for event in events] == sorted(
            event["offset_ms"] for event in events
        )
        assert all(event["actor_id"] in synthetic_actors for event in events)


def test_seed_changes_the_daily_trace() -> None:
    simulator = load_simulator()

    assert simulator.render_jsonl("daily", 1) != simulator.render_jsonl("daily", 2)


def test_smoke_scenario_uses_one_real_reply_and_keeps_transport_events() -> None:
    simulator = load_simulator()
    events = [json.loads(line) for line in simulator.render_jsonl("smoke", 20260813).splitlines()]
    replyable = {"danmaku", "gift", "super_chat"}

    assert sum(event["event_type"] in replyable for event in events) == 1
    assert {event["event_type"] for event in events} >= {
        "danmaku",
        "enter",
        "follow",
        "like_batch",
    }
    assert events[-1]["offset_ms"] <= 1_000


def test_non_replyable_events_remain_in_daily_transport_trace() -> None:
    simulator = load_simulator()
    events = [json.loads(line) for line in simulator.render_jsonl("daily", 20260813).splitlines()]

    assert {event["event_type"] for event in events} >= {
        "danmaku",
        "enter",
        "follow",
        "like_batch",
    }


def test_waited_start_reports_post_run_readiness(monkeypatch, capsys) -> None:
    simulator = load_simulator()

    def request(
        _base_url: str,
        path: str,
        *,
        method: str = "GET",
        payload=None,
        timeout: float = 15,
    ) -> dict:
        del method, payload, timeout
        if path == "/ready":
            return {"ready": True, "status": "ready", "profile": "production"}
        if path == "/api/program-replays/start":
            return {"replay_id": "replay-1", "state": "running"}
        if path == "/api/program-replays/replay-1":
            return {
                "replay_id": "replay-1",
                "state": "completed",
                "cursor": 4,
                "total_events": 4,
                "error": None,
            }
        raise AssertionError(path)

    monkeypatch.setattr(simulator, "_request", request)

    assert simulator.main(["start", "smoke", "--wait"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["runtime_ready_after"] is True
    assert result["runtime_status_after"] == {
        "profile": "production",
        "ready": True,
        "status": "ready",
    }


def test_waited_start_preserves_replay_result_when_runtime_drops(monkeypatch, capsys) -> None:
    simulator = load_simulator()
    ready_checks = 0

    def request(
        _base_url: str,
        path: str,
        *,
        method: str = "GET",
        payload=None,
        timeout: float = 15,
    ) -> dict:
        nonlocal ready_checks
        del method, payload, timeout
        if path == "/ready":
            ready_checks += 1
            if ready_checks == 1:
                return {"ready": True, "status": "ready", "profile": "production"}
            raise RuntimeError("无法连接 Animetta：connection refused")
        if path == "/api/program-replays/start":
            return {"replay_id": "replay-1", "state": "running"}
        if path == "/api/program-replays/replay-1":
            return {
                "replay_id": "replay-1",
                "state": "completed",
                "cursor": 4,
                "total_events": 4,
                "error": None,
            }
        raise AssertionError(path)

    monkeypatch.setattr(simulator, "_request", request)

    assert simulator.main(["start", "smoke", "--wait"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["replay_id"] == "replay-1"
    assert result["state"] == "completed"
    assert result["runtime_ready_after"] is False
    assert "connection refused" in result["runtime_error_after"]
