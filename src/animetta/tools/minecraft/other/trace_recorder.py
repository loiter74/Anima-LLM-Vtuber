"""
Trace Recorder - Records task execution traces for skill extraction

Records action-level and task-level traces to JSONL format for later
analysis and skill mining.  Each trace captures the goal, individual
actions with state snapshots, and final outcomes.

Usage:
    recorder = TraceRecorder()
    recorder.start_trace("mine 10 oak logs")
    recorder.record_action("collect", {"block_type": "oak_log", "count": 5}, ...)
    recorder.record_action("collect", {"block_type": "oak_log", "count": 5}, ...)
    trace = recorder.end_trace("success")
    await recorder.save_trace(trace)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

# Default trace output path
_DEFAULT_TRACE_PATH = Path("data/mc_traces.jsonl")


# ── Data Classes ──────────────────────────────────────────────────────────────


@dataclass
class ActionTrace:
    """Record of a single action within a task trace."""

    action: str
    params: dict[str, Any]
    result: Any
    duration: float
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return {
            "action": self.action,
            "params": self.params,
            "result": self.result,
            "duration": round(self.duration, 4),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "error": self.error,
        }


@dataclass
class TaskTrace:
    """Record of a complete task execution."""

    id: str
    goal: str
    steps: list[ActionTrace]
    final_result: str
    total_duration: float
    items_gained: dict[str, int]
    items_lost: dict[str, int]
    distance_traveled: float
    start_position: dict[str, float]
    end_position: dict[str, float]
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "final_result": self.final_result,
            "total_duration": round(self.total_duration, 4),
            "items_gained": self.items_gained,
            "items_lost": self.items_lost,
            "distance_traveled": round(self.distance_traveled, 2),
            "start_position": self.start_position,
            "end_position": self.end_position,
            "timestamp": self.timestamp,
        }


# ── Recorder ──────────────────────────────────────────────────────────────────


class TraceRecorder:
    """Records task execution traces and persists them to JSONL.

    Lifecycle:
        1. ``start_trace(goal)`` — begin recording a new task
        2. ``record_action(...)`` — record each action as it executes
        3. ``end_trace(result)`` — finalize and return the ``TaskTrace``
        4. ``save_trace(trace)`` — append to the JSONL file
    """

    def __init__(self, trace_path: str | Path | None = None):
        self._trace_path = Path(trace_path) if trace_path else _DEFAULT_TRACE_PATH
        self._current_goal: str | None = None
        self._steps: list[ActionTrace] = []
        self._start_time: float = 0.0
        self._start_position: dict[str, float] = {}
        self._last_position: dict[str, float] = {}
        self._last_inventory: dict[str, int] = {}
        self._distance_traveled: float = 0.0

        logger.info(f"[TraceRecorder] Initialized (path={self._trace_path})")

    # ── Recording lifecycle ───────────────────────────────────────────────

    def start_trace(self, goal: str) -> None:
        """Begin recording a new task trace.

        Resets internal state so a fresh trace can be captured.
        """
        if self._current_goal is not None:
            logger.warning(
                "[TraceRecorder] Overwriting unfinished trace for "
                f"'{self._current_goal}' — call end_trace() first"
            )

        self._current_goal = goal
        self._steps = []
        self._start_time = time.monotonic()
        self._start_position = {}
        self._last_position = {}
        self._last_inventory = {}
        self._distance_traveled = 0.0

        logger.info(f"[TraceRecorder] Started trace: {goal!r}")

    def record_action(
        self,
        action: str,
        params: dict[str, Any],
        result: Any,
        state_before: dict[str, Any],
        state_after: dict[str, Any],
        duration: float,
        error: str | None = None,
    ) -> None:
        """Record a single action within the current trace.

        Args:
            action: Action name (e.g. ``"collect"``, ``"goto"``).
            params: Parameters sent with the action.
            result: Result returned by the action.
            state_before: World state snapshot before the action.
            state_after: World state snapshot after the action.
            duration: Wall-clock duration of the action in seconds.
            error: Error message if the action failed, else ``None``.
        """
        if self._current_goal is None:
            logger.warning("[TraceRecorder] No active trace — call start_trace() first")
            return

        step = ActionTrace(
            action=action,
            params=params,
            result=result,
            duration=duration,
            state_before=state_before,
            state_after=state_after,
            error=error,
        )
        self._steps.append(step)

        # Track position changes for distance calculation
        self._update_position(state_after)
        # Track inventory changes
        self._update_inventory(state_after)

        logger.debug(
            f"[TraceRecorder] Recorded action: {action} "
            f"({'error' if error else 'ok'}, {duration:.2f}s)"
        )

    def end_trace(self, result: str) -> TaskTrace:
        """Finalize the current trace and return it.

        Args:
            result: Outcome description (e.g. ``"success"``, ``"failed: timeout"``).

        Returns:
            The completed ``TaskTrace``.

        Raises:
            RuntimeError: If no trace is currently being recorded.
        """
        if self._current_goal is None:
            raise RuntimeError("No active trace — call start_trace() first")

        total_duration = time.monotonic() - self._start_time

        # Compute item gains/losses from first and last inventory snapshots
        items_gained, items_lost = self._compute_inventory_delta()

        trace = TaskTrace(
            id=uuid.uuid4().hex[:12],
            goal=self._current_goal,
            steps=list(self._steps),
            final_result=result,
            total_duration=total_duration,
            items_gained=items_gained,
            items_lost=items_lost,
            distance_traveled=self._distance_traveled,
            start_position=dict(self._start_position),
            end_position=dict(self._last_position),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )

        logger.info(
            f"[TraceRecorder] Ended trace: {self._current_goal!r} → {result} "
            f"({len(self._steps)} steps, {total_duration:.2f}s, "
            f"dist={self._distance_traveled:.1f})"
        )

        # Reset state
        self._current_goal = None
        self._steps = []
        self._start_time = 0.0
        self._start_position = {}
        self._last_position = {}
        self._last_inventory = {}
        self._distance_traveled = 0.0

        return trace

    async def save_trace(self, trace: TaskTrace) -> None:
        """Append a trace to the JSONL file (non-blocking).

        Uses ``asyncio.to_thread`` to avoid blocking the event loop
        during file I/O.

        Args:
            trace: The ``TaskTrace`` to persist.
        """
        line = json.dumps(trace.to_dict(), ensure_ascii=False) + "\n"

        def _write() -> None:
            self._trace_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._trace_path, "a", encoding="utf-8") as f:
                f.write(line)

        await asyncio.to_thread(_write)
        logger.info(f"[TraceRecorder] Saved trace {trace.id} to {self._trace_path}")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _update_position(self, state: dict[str, Any]) -> None:
        """Track position changes and accumulate distance traveled."""
        x = state.get("x")
        y = state.get("y")
        z = state.get("z")

        if x is None or y is None or z is None:
            return

        pos = {"x": float(x), "y": float(y), "z": float(z)}

        if not self._start_position:
            self._start_position = dict(pos)

        if self._last_position:
            dx = pos["x"] - self._last_position["x"]
            dy = pos["y"] - self._last_position["y"]
            dz = pos["z"] - self._last_position["z"]
            self._distance_traveled += (dx**2 + dy**2 + dz**2) ** 0.5

        self._last_position = pos

    def _update_inventory(self, state: dict[str, Any]) -> None:
        """Track inventory snapshots for delta computation."""
        inventory = state.get("inventory")
        if isinstance(inventory, dict):
            self._last_inventory = dict(inventory)

    def _compute_inventory_delta(self) -> tuple[dict[str, int], dict[str, int]]:
        """Compute items gained and lost across the trace.

        Compares the first and last inventory snapshots recorded
        during action execution.

        Returns:
            Tuple of (items_gained, items_lost) dicts mapping item
            name to count.
        """
        if not self._steps:
            return {}, {}

        # Find the earliest "before" inventory and latest "after" inventory
        first_inv: dict[str, int] = {}
        last_inv: dict[str, int] = {}

        for step in self._steps:
            inv_before = step.state_before.get("inventory")
            if isinstance(inv_before, dict) and not first_inv:
                first_inv = dict(inv_before)

            inv_after = step.state_after.get("inventory")
            if isinstance(inv_after, dict):
                last_inv = dict(inv_after)

        if not first_inv and not last_inv:
            return {}, {}

        # If we never captured a "before" snapshot, use the first "after"
        if not first_inv:
            first_inv = {}

        all_items = set(first_inv) | set(last_inv)
        gained: dict[str, int] = {}
        lost: dict[str, int] = {}

        for item in all_items:
            before_count = first_inv.get(item, 0)
            after_count = last_inv.get(item, 0)
            diff = after_count - before_count
            if diff > 0:
                gained[item] = diff
            elif diff < 0:
                lost[item] = abs(diff)

        return gained, lost

    @property
    def is_recording(self) -> bool:
        """Whether a trace is currently being recorded."""
        return self._current_goal is not None
