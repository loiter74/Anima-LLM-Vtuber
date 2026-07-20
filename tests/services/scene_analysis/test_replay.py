from __future__ import annotations

import time
from dataclasses import dataclass

from animetta.services.scene_analysis.models import (
    LiveSceneState,
    NormalizedSceneEvent,
    SceneEvidence,
    SceneStatePatch,
)
from animetta.services.scene_analysis.runtime import SceneRuntime


@dataclass
class MutableClock:
    value: float = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def event(seq: int, *, now: float, text: str) -> NormalizedSceneEvent:
    return NormalizedSceneEvent(
        event_id=f"replay-{seq}",
        event_seq=seq,
        session_id="replay-1",
        room_id=42,
        generation_id=1,
        occurred_at=now,
        event_type="danmaku",
        actor_id=f"anonymous-{seq % 7}",
        text=text,
    )


class LifecycleGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def reflect(
        self,
        evidence: SceneEvidence,
        state: LiveSceneState,
    ) -> SceneStatePatch:
        self.calls += 1
        count = evidence.to_event_seq
        lifecycle = "rising" if count < 60 else "overused"
        return SceneStatePatch(
            base_revision=state.state_revision,
            consumed_event_seq=evidence.to_event_seq,
            scene_stage="topic_rising" if count < 60 else "cooldown",
            scene_summary="The shared joke is active." if count < 60 else "The joke is saturated.",
            meme_upserts=[
                {
                    "meme_id": "clipping",
                    "label": "穿模",
                    "lifecycle": lifecycle,
                    "mentions": count,
                    "last_event_seq": evidence.to_event_seq,
                }
            ],
            confidence=0.9,
            generated_at=evidence.representative_events[-1].occurred_at,
        )


async def test_anonymous_replay_reduces_calls_and_tracks_meme_lifecycle() -> None:
    clock = MutableClock()
    gateway = LifecycleGateway()
    runtime = SceneRuntime(
        session_id="replay-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        event_threshold=30,
        reflection_interval_seconds=30,
        max_reflections_per_minute=4,
        clock=clock,
    )

    for seq in range(1, 91):
        await runtime.observe(event(seq, now=clock(), text="穿模"))
        clock.advance(0.2)
        if seq % 30 == 0:
            await runtime.wait_idle()
    await runtime.wait_idle()

    snapshot = runtime.snapshot()
    guidance = await runtime.guidance_for_reply()
    assert gateway.calls <= 27  # at least 70% fewer than per-event reflection
    assert gateway.calls == 3
    assert snapshot.scene_stage == "cooldown"
    assert snapshot.meme_states[0].lifecycle == "overused"
    assert guidance is not None
    assert guidance.response_objective == "Close the saturated beat and transition naturally."
    assert guidance.scope.max_sentences == 2
    assert guidance.scope.max_chars == 180
    assert guidance.scope.allow_topic_switch is False
    assert guidance.meme_policy.action == "avoid"


async def test_cached_guidance_path_p95_is_below_fifty_milliseconds() -> None:
    clock = MutableClock()
    gateway = LifecycleGateway()
    runtime = SceneRuntime(
        session_id="replay-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        event_threshold=1,
        clock=clock,
    )
    await runtime.observe(event(1, now=clock(), text="穿模"))
    await runtime.wait_idle()

    durations_ms: list[float] = []
    for _ in range(200):
        started = time.perf_counter()
        assert await runtime.guidance_for_reply() is not None
        durations_ms.append((time.perf_counter() - started) * 1000)

    p95_ms = sorted(durations_ms)[int(len(durations_ms) * 0.95) - 1]
    assert p95_ms < 50
