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


def test_hourly_scenario_has_sixty_fixed_messages_and_heat_adaptation() -> None:
    simulator = load_simulator()
    events = simulator.build_scenario("hourly", 20260813)
    fixed = [event for event in events if event["payload"].get("cadence") == "fixed"]
    adaptive = [event for event in events if event["payload"].get("cadence") == "adaptive"]
    snapshots = [event for event in events if event["event_type"] == "popularity_snapshot"]

    assert len(fixed) == 60
    assert [event["offset_ms"] for event in fixed] == [minute * 60_000 for minute in range(60)]
    assert len(adaptive) == 60
    assert len(snapshots) == 60
    assert events[-1]["offset_ms"] == 3_600_000
    assert events[-1]["event_type"] == "connection_state"
    assert simulator.scenario_metrics("hourly", 20260813) == {
        "events": 181,
        "replyable_events": 120,
        "duration_seconds": 3600.0,
        "fixed_events": 60,
        "adaptive_events": 60,
        "heat_minutes": {"low": 15, "medium": 30, "high": 15},
    }

    for snapshot in snapshots:
        minute = snapshot["payload"]["minute"]
        tier = snapshot["payload"]["heat_tier"]
        minute_adaptive = [event for event in adaptive if event["payload"]["minute"] == minute]
        assert len(minute_adaptive) == simulator.HEAT_EXTRA_EVENTS[tier]


def test_hourly_wait_timeout_covers_timeline_plus_provider_allowance() -> None:
    simulator = load_simulator()

    assert simulator.default_timeout_seconds("hourly", 20260813, 1) == 4500
    assert simulator.default_timeout_seconds("smoke", 20260813, 100) == 900


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
