"""Tests for TraceRecorder — task execution trace recording and persistence."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from animetta.tools.minecraft.other.trace_recorder import (
    ActionTrace,
    TaskTrace,
    TraceRecorder,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(
    x: float = 0,
    y: float = 64,
    z: float = 0,
    inventory: dict[str, int] | None = None,
) -> dict:
    """Build a minimal state snapshot."""
    state: dict = {"x": x, "y": y, "z": z}
    if inventory is not None:
        state["inventory"] = inventory
    return state


def _record_simple_action(
    recorder: TraceRecorder,
    action: str = "collect",
    params: dict | None = None,
    result: str = "success",
    before_inv: dict | None = None,
    after_inv: dict | None = None,
    pos: tuple[float, float, float] = (0, 64, 0),
    duration: float = 1.0,
    error: str | None = None,
) -> None:
    """Convenience: record a single action with minimal boilerplate."""
    recorder.record_action(
        action=action,
        params=params or {"block_type": "oak_log", "count": 5},
        result=result,
        state_before=_make_state(inventory=before_inv),
        state_after=_make_state(*pos, inventory=after_inv),
        duration=duration,
        error=error,
    )


# ── ActionTrace ──────────────────────────────────────────────────────────────


class TestActionTrace:
    """ActionTrace dataclass tests."""

    def test_to_dict_roundtrip(self):
        trace = ActionTrace(
            action="goto",
            params={"x": 10, "y": 64, "z": -5},
            result="Arrived",
            duration=2.3456,
            state_before={"x": 0, "y": 64, "z": 0},
            state_after={"x": 10, "y": 64, "z": -5},
            error=None,
        )
        d = trace.to_dict()
        assert d["action"] == "goto"
        assert d["params"] == {"x": 10, "y": 64, "z": -5}
        assert d["result"] == "Arrived"
        assert d["duration"] == 2.3456
        assert d["error"] is None

    def test_to_dict_with_error(self):
        trace = ActionTrace(
            action="mine",
            params={},
            result=None,
            duration=0.5,
            state_before={},
            state_after={},
            error="Timeout after 60s",
        )
        d = trace.to_dict()
        assert d["error"] == "Timeout after 60s"


# ── TaskTrace ────────────────────────────────────────────────────────────────


class TestTaskTrace:
    """TaskTrace dataclass tests."""

    def test_to_dict_basic(self):
        trace = TaskTrace(
            id="abc123",
            goal="mine stone",
            steps=[],
            final_result="success",
            total_duration=10.0,
            items_gained={"cobblestone": 10},
            items_lost={},
            distance_traveled=45.2,
            start_position={"x": 0, "y": 64, "z": 0},
            end_position={"x": 10, "y": 60, "z": 5},
            timestamp="2026-01-01T00:00:00",
        )
        d = trace.to_dict()
        assert d["id"] == "abc123"
        assert d["goal"] == "mine stone"
        assert d["items_gained"] == {"cobblestone": 10}
        assert d["distance_traveled"] == 45.2

    def test_to_dict_includes_nested_steps(self):
        step = ActionTrace(
            action="goto",
            params={"x": 5},
            result="ok",
            duration=1.0,
            state_before={},
            state_after={},
        )
        trace = TaskTrace(
            id="x",
            goal="test",
            steps=[step],
            final_result="ok",
            total_duration=1.0,
            items_gained={},
            items_lost={},
            distance_traveled=0.0,
            start_position={},
            end_position={},
        )
        d = trace.to_dict()
        assert len(d["steps"]) == 1
        assert d["steps"][0]["action"] == "goto"


# ── TraceRecorder ────────────────────────────────────────────────────────────


class TestTraceRecorderInit:
    """Recorder initialisation tests."""

    def test_default_path(self):
        recorder = TraceRecorder()
        assert recorder._trace_path == Path("data/mc_traces.jsonl")

    def test_custom_path(self, tmp_path: Path):
        p = tmp_path / "custom.jsonl"
        recorder = TraceRecorder(trace_path=p)
        assert recorder._trace_path == p

    def test_initial_state(self):
        recorder = TraceRecorder()
        assert recorder.is_recording is False
        assert recorder._current_goal is None


class TestTraceRecorderStartTrace:
    """start_trace() tests."""

    def test_start_sets_goal(self):
        recorder = TraceRecorder()
        recorder.start_trace("collect 10 oak logs")
        assert recorder.is_recording is True
        assert recorder._current_goal == "collect 10 oak logs"

    def test_start_resets_state(self):
        recorder = TraceRecorder()
        recorder.start_trace("first task")
        _record_simple_action(recorder, pos=(5, 64, 5))
        # Start a new trace — old steps should be cleared
        recorder.start_trace("second task")
        assert len(recorder._steps) == 0
        assert recorder._distance_traveled == 0.0

    def test_start_overwrites_unfinished(self):
        recorder = TraceRecorder()
        recorder.start_trace("task 1")
        recorder.start_trace("task 2")
        assert recorder._current_goal == "task 2"


class TestTraceRecorderRecordAction:
    """record_action() tests."""

    def test_record_action_appends_step(self):
        recorder = TraceRecorder()
        recorder.start_trace("test")
        _record_simple_action(recorder)
        assert len(recorder._steps) == 1
        assert recorder._steps[0].action == "collect"

    def test_record_without_start_is_noop(self):
        recorder = TraceRecorder()
        _record_simple_action(recorder)
        assert len(recorder._steps) == 0

    def test_record_multiple_actions(self):
        recorder = TraceRecorder()
        recorder.start_trace("test")
        _record_simple_action(recorder, action="goto", duration=2.0)
        _record_simple_action(recorder, action="collect", duration=5.0)
        assert len(recorder._steps) == 2


class TestTraceRecorderEndTrace:
    """end_trace() tests."""

    def test_end_returns_task_trace(self):
        recorder = TraceRecorder()
        recorder.start_trace("mine stone")
        _record_simple_action(recorder)
        trace = recorder.end_trace("success")
        assert isinstance(trace, TaskTrace)
        assert trace.goal == "mine stone"
        assert trace.final_result == "success"
        assert len(trace.steps) == 1

    def test_end_resets_recorder(self):
        recorder = TraceRecorder()
        recorder.start_trace("test")
        recorder.end_trace("done")
        assert recorder.is_recording is False
        assert recorder._current_goal is None

    def test_end_without_start_raises(self):
        recorder = TraceRecorder()
        with pytest.raises(RuntimeError, match="No active trace"):
            recorder.end_trace("success")

    def test_end_populates_timestamp(self):
        recorder = TraceRecorder()
        recorder.start_trace("test")
        trace = recorder.end_trace("ok")
        assert trace.timestamp  # Non-empty string

    def test_end_has_unique_id(self):
        recorder = TraceRecorder()
        recorder.start_trace("test")
        t1 = recorder.end_trace("ok")
        recorder.start_trace("test2")
        t2 = recorder.end_trace("ok")
        assert t1.id != t2.id


class TestTraceRecorderSaveTrace:
    """save_trace() tests."""

    async def test_save_creates_file(self, tmp_path: Path):
        p = tmp_path / "traces.jsonl"
        recorder = TraceRecorder(trace_path=p)
        trace = TaskTrace(
            id="test1",
            goal="test",
            steps=[],
            final_result="ok",
            total_duration=1.0,
            items_gained={},
            items_lost={},
            distance_traveled=0.0,
            start_position={},
            end_position={},
            timestamp="2026-01-01T00:00:00",
        )
        await recorder.save_trace(trace)
        assert p.exists()

    async def test_save_writes_valid_jsonl(self, tmp_path: Path):
        p = tmp_path / "traces.jsonl"
        recorder = TraceRecorder(trace_path=p)
        trace = TaskTrace(
            id="test2",
            goal="collect wood",
            steps=[],
            final_result="success",
            total_duration=5.0,
            items_gained={"oak_log": 10},
            items_lost={},
            distance_traveled=12.5,
            start_position={"x": 0, "y": 64, "z": 0},
            end_position={"x": 10, "y": 64, "z": 5},
            timestamp="2026-01-01T00:00:00",
        )
        await recorder.save_trace(trace)
        content = p.read_text(encoding="utf-8").strip()
        data = json.loads(content)
        assert data["id"] == "test2"
        assert data["goal"] == "collect wood"
        assert data["items_gained"] == {"oak_log": 10}

    async def test_save_appends_multiple(self, tmp_path: Path):
        p = tmp_path / "traces.jsonl"
        recorder = TraceRecorder(trace_path=p)
        for i in range(3):
            trace = TaskTrace(
                id=f"t{i}",
                goal=f"task {i}",
                steps=[],
                final_result="ok",
                total_duration=1.0,
                items_gained={},
                items_lost={},
                distance_traveled=0.0,
                start_position={},
                end_position={},
            )
            await recorder.save_trace(trace)
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3


class TestTraceRecorderInventoryTracking:
    """Inventory gain/loss tracking tests."""

    def test_items_gained(self):
        recorder = TraceRecorder()
        recorder.start_trace("collect wood")
        _record_simple_action(
            recorder,
            before_inv={"oak_log": 0},
            after_inv={"oak_log": 5},
        )
        trace = recorder.end_trace("success")
        assert trace.items_gained == {"oak_log": 5}

    def test_items_lost(self):
        recorder = TraceRecorder()
        recorder.start_trace("place blocks")
        _record_simple_action(
            recorder,
            before_inv={"cobblestone": 9},
            after_inv={"cobblestone": 0},
        )
        trace = recorder.end_trace("success")
        assert trace.items_lost == {"cobblestone": 9}

    def test_net_change_multiple_items(self):
        recorder = TraceRecorder()
        recorder.start_trace("craft")
        _record_simple_action(
            recorder,
            before_inv={"oak_log": 10, "oak_planks": 0},
            after_inv={"oak_log": 7, "oak_planks": 12},
        )
        trace = recorder.end_trace("success")
        assert trace.items_gained == {"oak_planks": 12}
        assert trace.items_lost == {"oak_log": 3}

    def test_no_inventory_data_returns_empty(self):
        recorder = TraceRecorder()
        recorder.start_trace("walk around")
        _record_simple_action(recorder, before_inv=None, after_inv=None)
        trace = recorder.end_trace("success")
        assert trace.items_gained == {}
        assert trace.items_lost == {}


class TestTraceRecorderDistanceTracking:
    """Distance travelled tracking tests."""

    def test_no_movement_zero_distance(self):
        recorder = TraceRecorder()
        recorder.start_trace("stay still")
        _record_simple_action(recorder, pos=(0, 64, 0))
        trace = recorder.end_trace("ok")
        assert trace.distance_traveled == 0.0

    def test_linear_movement(self):
        recorder = TraceRecorder()
        recorder.start_trace("walk")
        # First action sets start position; second measures distance from it
        _record_simple_action(recorder, pos=(0, 64, 0))
        _record_simple_action(recorder, pos=(10, 64, 0))
        trace = recorder.end_trace("ok")
        assert math.isclose(trace.distance_traveled, 10.0, abs_tol=0.01)

    def test_diagonal_movement(self):
        recorder = TraceRecorder()
        recorder.start_trace("walk diagonal")
        _record_simple_action(recorder, pos=(0, 64, 0))
        _record_simple_action(recorder, pos=(3, 64, 4))
        trace = recorder.end_trace("ok")
        assert math.isclose(trace.distance_traveled, 5.0, abs_tol=0.01)

    def test_cumulative_distance(self):
        recorder = TraceRecorder()
        recorder.start_trace("multi-hop")
        # First action sets start; subsequent actions accumulate distance
        _record_simple_action(recorder, pos=(0, 64, 0))
        _record_simple_action(recorder, pos=(10, 64, 0))
        _record_simple_action(recorder, pos=(10, 64, 10))
        trace = recorder.end_trace("ok")
        # 10 (origin→10,64,0) + 10 (10,64,0→10,64,10) = 20
        assert math.isclose(trace.distance_traveled, 20.0, abs_tol=0.01)

    def test_start_end_positions(self):
        recorder = TraceRecorder()
        recorder.start_trace("move")
        # First recorded position becomes start_position
        _record_simple_action(recorder, pos=(5, 64, 0))
        _record_simple_action(recorder, pos=(10, 64, 5))
        trace = recorder.end_trace("ok")
        assert trace.start_position == {"x": 5.0, "y": 64.0, "z": 0.0}
        assert trace.end_position == {"x": 10.0, "y": 64.0, "z": 5.0}
