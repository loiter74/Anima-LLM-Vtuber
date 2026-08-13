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


def test_non_replyable_events_remain_in_daily_transport_trace() -> None:
    simulator = load_simulator()
    events = [json.loads(line) for line in simulator.render_jsonl("daily", 20260813).splitlines()]

    assert {event["event_type"] for event in events} >= {
        "danmaku",
        "enter",
        "follow",
        "like_batch",
    }
