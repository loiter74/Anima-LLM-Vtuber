from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from animetta.services.livestream_narration import (
    BroadcastNarrationDirector,
    NarrationCue,
)


def _projection(
    sequence: int = 1,
    *,
    phase: str = "observing",
    outcome: str = "active",
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "event": "minecraft.activity.projection",
        "event_id": f"activity:{sequence}",
        "projection_kind": "activity",
        "projection_version": sequence,
        "occurred_at_ms": 1000 + sequence,
        "mission_id": "mission-public",
        "entity_id": "minecraft",
        "payload": {
            "phase": phase,
            "intent": "acquire",
            "focus": {"kind": "item", "label": "橡木"},
            "outcome": outcome,
        },
    }


@pytest.mark.asyncio
async def test_visual_only_emits_safe_activity_and_replay_once() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    director = BroadcastNarrationDirector(emit, mode="visual_only")
    await director.submit(_projection())
    await director.submit(_projection())

    assert [event for event, _, _ in emitted] == [
        "minecraft:activity_projection",
        "livestream:narration_state",
    ]
    assert emitted[1][1]["visual_text"] == "先看看橡木周围的情况。"

    await director.replay("public-sid")
    assert [to for _, _, to in emitted[-2:]] == ["public-sid", "public-sid"]


@pytest.mark.asyncio
async def test_replay_limit_can_be_reconfigured_without_replaying_evicted_events() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    director = BroadcastNarrationDirector(emit, mode="visual_only", replay_limit=3)
    for sequence in range(1, 4):
        await director.submit(_projection(sequence))
    director.configure("visual_only", replay_limit=2)
    emitted.clear()

    await director.replay("public-sid")

    assert director.replay_limit == 2
    assert [
        payload["event_id"]
        for event, payload, _ in emitted
        if event == "minecraft:activity_projection"
    ] == ["activity:2", "activity:3"]


@pytest.mark.asyncio
async def test_off_mode_does_not_replay_cached_or_persisted_activity() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    director = BroadcastNarrationDirector(emit, mode="visual_only")
    await director.submit(_projection())
    emitted.clear()

    director.configure("off")
    await director.replay("public-sid")
    await director.replay_persisted([_projection(2)], "public-sid")

    assert emitted == []


@pytest.mark.asyncio
async def test_submit_rejects_stale_sequence_after_terminal_activity() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []
    spoken: list[str] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    async def speaker(cue: NarrationCue, on_started: Callable[[], Awaitable[None]]) -> str:
        await on_started()
        spoken.append(cue.source_event_id)
        return cue.visual_text

    terminal = _projection(2, phase="finished", outcome="succeeded")
    stale = _projection(1, phase="acting")
    director = BroadcastNarrationDirector(emit, speaker=speaker, mode="full")

    await director.submit(terminal)
    await director.submit(stale)
    await asyncio.sleep(0.05)

    assert [
        payload["event_id"]
        for event, payload, _ in emitted
        if event == "minecraft:activity_projection"
    ] == ["activity:2"]
    assert spoken == ["activity:2"]
    await director.close()


@pytest.mark.asyncio
async def test_persisted_replay_uses_global_sequence_order() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    director = BroadcastNarrationDirector(emit, mode="visual_only")
    await director.replay_persisted([_projection(2), _projection(1)], "public-sid")

    assert [
        payload["event_id"]
        for event, payload, _ in emitted
        if event == "minecraft:activity_projection"
    ] == ["activity:1", "activity:2"]


@pytest.mark.asyncio
async def test_persisted_replay_fences_a_late_stale_live_event() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    director = BroadcastNarrationDirector(emit, mode="visual_only")
    await director.replay_persisted(
        [_projection(2, phase="finished", outcome="succeeded")],
        "public-sid",
    )
    await director.submit(_projection(1, phase="acting"))

    assert [
        (payload["event_id"], to)
        for event, payload, to in emitted
        if event == "minecraft:activity_projection"
    ] == [("activity:2", "public-sid")]


@pytest.mark.asyncio
async def test_projection_version_must_match_event_sequence() -> None:
    async def emit(_event: str, _payload: dict[str, Any], _to: str | None) -> None:
        return None

    invalid = _projection(2)
    invalid["projection_version"] = 1
    director = BroadcastNarrationDirector(emit, mode="visual_only")

    with pytest.raises(ValueError, match="sequence"):
        await director.submit(invalid)


@pytest.mark.asyncio
async def test_full_mode_speaks_only_sanitized_cue() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []
    spoken = asyncio.Event()
    received: list[NarrationCue] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    async def speaker(cue: NarrationCue, on_started) -> str:
        received.append(cue)
        await on_started()
        spoken.set()
        return cue.visual_text

    director = BroadcastNarrationDirector(emit, mode="full", speaker=speaker)
    await director.submit(_projection())
    await asyncio.wait_for(spoken.wait(), timeout=1)
    await asyncio.sleep(0)

    assert received[0].visual_text == "先看看橡木周围的情况。"
    assert any(
        event == "livestream:narration_state" and payload["speech_state"] == "completed"
        for event, payload, _ in emitted
    )
    await director.close()


@pytest.mark.asyncio
async def test_composer_timeout_keeps_visual_state_and_cancels_speech() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    async def unavailable(_cue: NarrationCue, _on_started) -> None:
        return None

    director = BroadcastNarrationDirector(emit, mode="full", speaker=unavailable)
    await director.submit(_projection())
    await asyncio.sleep(0.1)

    narration = [payload for event, payload, _ in emitted if event == "livestream:narration_state"]
    assert narration[0]["visual_text"] == "先看看橡木周围的情况。"
    assert narration[-1]["speech_state"] == "cancelled"
    await director.close()


@pytest.mark.asyncio
async def test_private_activity_fields_are_rejected() -> None:
    async def emit(_event: str, _payload: dict[str, Any], _to: str | None) -> None:
        return None

    director = BroadcastNarrationDirector(emit, mode="visual_only")
    projection = _projection()
    projection["payload"]["reasoning"] = "hidden"

    with pytest.raises(ValueError, match="private fields"):
        await director.submit(projection)


@pytest.mark.asyncio
async def test_finished_activity_requires_terminal_outcome() -> None:
    async def emit(_event: str, _payload: dict[str, Any], _to: str | None) -> None:
        return None

    director = BroadcastNarrationDirector(emit, mode="visual_only")
    with pytest.raises(ValueError, match="terminal outcome"):
        await director.submit(_projection(phase="finished"))


@pytest.mark.asyncio
async def test_new_progress_supersedes_one_pending_mission_cue() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []
    blocked = True
    spoken: list[str] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    async def speaker(cue: NarrationCue, on_started) -> str:
        await on_started()
        spoken.append(cue.source_event_id)
        return cue.visual_text

    director = BroadcastNarrationDirector(
        emit,
        mode="full",
        speaker=speaker,
        busy=lambda: blocked,
    )
    await director.submit(_projection(1, phase="observing"))
    await asyncio.sleep(0)
    await director.submit(_projection(2, phase="acting"))
    blocked = False
    await asyncio.sleep(0.2)

    assert spoken == ["activity:2"]
    cancelled_sources = {
        payload["source_event_id"]
        for event, payload, _ in emitted
        if event == "livestream:narration_state" and payload.get("speech_state") == "cancelled"
    }
    assert "activity:1" not in cancelled_sources
    await director.close()


@pytest.mark.asyncio
async def test_failed_partial_delivery_is_retried_before_dedupe_commit() -> None:
    emitted: list[str] = []
    fail_narration_once = True

    async def emit(event: str, _payload: dict[str, Any], _to: str | None) -> None:
        nonlocal fail_narration_once
        emitted.append(event)
        if event == "livestream:narration_state" and fail_narration_once:
            fail_narration_once = False
            raise RuntimeError("socket unavailable")

    director = BroadcastNarrationDirector(emit, mode="visual_only")
    with pytest.raises(RuntimeError, match="socket unavailable"):
        await director.submit(_projection())

    await director.submit(_projection())

    assert emitted == [
        "minecraft:activity_projection",
        "livestream:narration_state",
        "minecraft:activity_projection",
        "livestream:narration_state",
    ]


@pytest.mark.asyncio
async def test_mode_downgrade_cancels_pending_cue_before_speech() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []
    blocked = True
    spoken = False

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    async def speaker(_cue: NarrationCue, on_started) -> str:
        nonlocal spoken
        await on_started()
        spoken = True
        return "不应播放"

    director = BroadcastNarrationDirector(
        emit,
        mode="full",
        speaker=speaker,
        busy=lambda: blocked,
    )
    await director.submit(_projection())
    await asyncio.sleep(0)

    director.configure("off")
    blocked = False
    await asyncio.sleep(0.05)

    assert not spoken
    assert any(
        event == "livestream:narration_state" and payload.get("speech_state") == "cancelled"
        for event, payload, _ in emitted
    )


@pytest.mark.asyncio
async def test_speaking_state_waits_for_media_start_boundary() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []
    release_media = asyncio.Event()

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    async def speaker(cue: NarrationCue, on_started) -> str:
        await release_media.wait()
        await on_started()
        return cue.visual_text

    director = BroadcastNarrationDirector(emit, mode="full", speaker=speaker)
    await director.submit(_projection())
    await asyncio.sleep(0)

    assert not any(
        event == "livestream:narration_state" and payload.get("speech_state") == "speaking"
        for event, payload, _ in emitted
    )

    release_media.set()
    await asyncio.sleep(0.05)
    assert any(
        event == "livestream:narration_state" and payload.get("speech_state") == "speaking"
        for event, payload, _ in emitted
    )
    await director.close()


@pytest.mark.asyncio
async def test_persisted_replay_skips_one_invalid_record() -> None:
    emitted: list[tuple[str, dict[str, Any], str | None]] = []

    async def emit(event: str, payload: dict[str, Any], to: str | None) -> None:
        emitted.append((event, payload, to))

    invalid = _projection(1)
    invalid["payload"]["reasoning"] = "private"
    director = BroadcastNarrationDirector(emit, mode="visual_only")

    await director.replay_persisted([invalid, _projection(2)], "public-sid")

    assert [
        (
            event,
            payload["source_event_id"] if event.startswith("livestream") else payload["event_id"],
        )
        for event, payload, _ in emitted
    ] == [
        ("minecraft:activity_projection", "activity:2"),
        ("livestream:narration_state", "activity:2"),
    ]
