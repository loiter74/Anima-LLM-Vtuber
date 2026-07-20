from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from animetta.services.bilibili.models import DanmakuMessage
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


class RecordingGateway:
    def __init__(self, *, delay: float = 0, fail_code: str | None = None) -> None:
        self.calls: list[tuple[SceneEvidence, LiveSceneState]] = []
        self.delay = delay
        self.fail_code = fail_code

    async def reflect(
        self,
        evidence: SceneEvidence,
        state: LiveSceneState,
    ) -> SceneStatePatch:
        self.calls.append((evidence, state))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_code:
            from animetta.services.scene_analysis.model_gateway import SceneModelGatewayError

            raise SceneModelGatewayError(self.fail_code)
        return SceneStatePatch(
            base_revision=state.state_revision,
            consumed_event_seq=evidence.to_event_seq,
            scene_stage="topic_rising",
            pace="fast",
            atmosphere="playful",
            engagement_level="high",
            engagement_trend="rising",
            scene_summary="The room is building a shared joke.",
            confidence=0.85,
            generated_at=evidence.representative_events[-1].occurred_at,
        )


def event(
    seq: int,
    *,
    now: float,
    text: str = "哈哈穿模了",
    critical: bool = False,
    generation_id: int = 1,
) -> NormalizedSceneEvent:
    return NormalizedSceneEvent(
        event_id=f"event-{generation_id}-{seq}",
        event_seq=seq,
        session_id="live-1",
        room_id=42 if generation_id == 1 else 43,
        generation_id=generation_id,
        occurred_at=now,
        event_type="super_chat" if critical else "danmaku",
        actor_id=f"viewer-{seq % 4}",
        text=text,
        critical=critical,
    )


async def test_evidence_includes_all_events_and_rule_hits() -> None:
    clock = MutableClock()
    gateway = RecordingGateway()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        event_threshold=3,
        clock=clock,
    )

    for seq in range(1, 4):
        await runtime.observe(event(seq, now=clock(), text="哈哈穿模了"))
        clock.advance(1)
    await runtime.wait_idle()

    assert len(gateway.calls) == 1
    evidence, _ = gateway.calls[0]
    assert evidence.metrics.event_count == 3
    assert evidence.metrics.unique_users == 3
    assert evidence.metrics.repeat_ratio == 1
    assert any(hit.rule == "repeated_phrase" for hit in evidence.rule_hits)
    assert [item.event_seq for item in evidence.representative_events] == [1, 2, 3]


async def test_critical_and_duplicate_triggers_are_single_flight() -> None:
    clock = MutableClock()
    gateway = RecordingGateway(delay=0.03)
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        event_threshold=30,
        clock=clock,
    )

    await runtime.observe(event(1, now=clock(), critical=True))
    await runtime.observe(event(2, now=clock(), critical=True))
    await runtime.observe(event(3, now=clock(), critical=True))
    await runtime.wait_idle()

    assert len(gateway.calls) == 1


async def test_trigger_during_reflection_coalesces_into_one_follow_up() -> None:
    clock = MutableClock()
    gateway = RecordingGateway(delay=0.03)
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        event_threshold=30,
        clock=clock,
    )

    await runtime.observe(event(1, now=clock(), critical=True))
    while not gateway.calls:
        await asyncio.sleep(0)
    await runtime.observe(event(2, now=clock(), critical=True))
    await runtime.wait_idle()

    assert len(gateway.calls) == 2
    assert gateway.calls[1][0].from_event_seq == 2
    assert gateway.calls[1][0].to_event_seq == 2


async def test_periodic_trigger_and_four_per_minute_budget() -> None:
    clock = MutableClock()
    gateway = RecordingGateway()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        reflection_interval_seconds=10,
        event_threshold=99,
        max_reflections_per_minute=4,
        clock=clock,
    )

    for seq in range(1, 7):
        clock.advance(11)
        await runtime.observe(event(seq, now=clock()))
        await runtime.wait_idle()

    assert len(gateway.calls) == 4
    assert runtime.metrics.rate_limited_triggers == 2


async def test_guidance_wait_timeout_uses_old_cache_with_rule_delta() -> None:
    clock = MutableClock()
    gateway = RecordingGateway(delay=0.08)
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        guidance_wait_seconds=0.01,
        clock=clock,
    )

    await runtime.observe(event(1, now=clock(), critical=True))
    guidance = await runtime.guidance_for_reply()

    assert guidance is not None
    assert guidance.degraded is True
    assert "refresh_timeout" in guidance.degradation_reasons
    assert guidance.must_address == ["Acknowledge the paid or critical event."]
    await runtime.wait_idle()


async def test_generation_reset_cancels_old_patch_and_clears_state() -> None:
    clock = MutableClock()
    gateway = RecordingGateway(delay=0.03)
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        clock=clock,
    )

    await runtime.observe(event(1, now=clock(), critical=True))
    await runtime.switch_generation(room_id=43, generation_id=2)
    await runtime.wait_idle()

    snapshot = runtime.snapshot()
    assert snapshot.room_id == 43
    assert snapshot.generation_id == 2
    assert snapshot.state_revision == 0
    assert snapshot.last_event_seq == 0
    assert runtime.event_count == 0


async def test_model_failure_produces_degraded_cached_guidance() -> None:
    clock = MutableClock()
    gateway = RecordingGateway(fail_code="provider_error")
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        clock=clock,
    )

    await runtime.observe(event(1, now=clock(), critical=True))
    await runtime.wait_idle()
    guidance = await runtime.guidance_for_reply()

    assert guidance is not None
    assert guidance.degraded is True
    assert "provider_error" in guidance.degradation_reasons


async def test_expired_cache_uses_rule_fallback_with_explicit_reason() -> None:
    clock = MutableClock()
    gateway = RecordingGateway()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        event_threshold=1,
        clock=clock,
    )
    await runtime.observe(event(1, now=clock()))
    await runtime.wait_idle()
    clock.advance(61)

    guidance = await runtime.guidance_for_reply()

    assert guidance is not None
    assert guidance.degraded is True
    assert "cache_expired" in guidance.degradation_reasons


async def test_shadow_mode_builds_cache_but_does_not_inject() -> None:
    clock = MutableClock()
    gateway = RecordingGateway()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="shadow",
        event_threshold=1,
        clock=clock,
    )

    await runtime.observe(event(1, now=clock()))
    await runtime.wait_idle()

    assert runtime.latest_guidance is not None
    assert await runtime.guidance_for_reply() is None


async def test_off_mode_never_schedules_reflection_or_injects_guidance() -> None:
    clock = MutableClock()
    gateway = RecordingGateway()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="off",
        event_threshold=1,
        clock=clock,
    )

    assert await runtime.observe(event(1, now=clock(), critical=True)) is True
    await runtime.wait_idle()

    assert runtime.event_count == 1
    assert gateway.calls == []
    assert runtime.latest_guidance is None
    assert await runtime.guidance_for_reply() is None


@pytest.mark.parametrize(
    ("message", "expected_type", "expected_amount", "expected_critical"),
    [
        (
            DanmakuMessage(text="普通弹幕", user_id=1, timestamp=100.0),
            "danmaku",
            None,
            False,
        ),
        (
            DanmakuMessage(
                text="赠送礼物",
                user_id=2,
                timestamp=100.0,
                is_gift=True,
                meta={"amount": 120},
            ),
            "gift",
            120,
            True,
        ),
        (
            DanmakuMessage(
                text="醒目留言",
                user_id=3,
                timestamp=100.0,
                is_super_chat=True,
                meta={"price": 30},
            ),
            "super_chat",
            30,
            True,
        ),
    ],
)
async def test_bilibili_events_are_normalized_before_reflection(
    message: DanmakuMessage,
    expected_type: str,
    expected_amount: float | None,
    expected_critical: bool,
) -> None:
    gateway = RecordingGateway()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        event_threshold=1,
        clock=MutableClock(),
    )

    assert await runtime.observe_danmaku(message, room_id=42, generation_id=1) is True
    await runtime.wait_idle()

    evidence, _ = gateway.calls[0]
    normalized = evidence.representative_events[-1]
    assert normalized.event_type == expected_type
    assert normalized.amount == expected_amount
    assert normalized.critical is expected_critical


class EmptyRetriever:
    def select(self, state: LiveSceneState, evidence: SceneEvidence | None):
        del state, evidence
        return None


async def test_empty_rag_results_stay_bounded_and_degrade_explicitly() -> None:
    clock = MutableClock()
    gateway = RecordingGateway()
    empty = EmptyRetriever()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=gateway,
        mode="active",
        event_threshold=1,
        clock=clock,
        technique_retriever=empty,
        meme_retriever=empty,
    )

    await runtime.observe(event(1, now=clock()))
    await runtime.wait_idle()
    guidance = await runtime.guidance_for_reply()

    assert guidance is not None
    assert guidance.technique is None
    assert guidance.meme_policy.action == "none"
    assert guidance.degraded is True
    assert "technique_rag_empty" in guidance.degradation_reasons
    assert "meme_rag_empty" in guidance.degradation_reasons


async def test_gateway_binding_only_runs_a_previously_triggered_refresh() -> None:
    clock = MutableClock()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=None,
        mode="active",
        event_threshold=30,
        clock=clock,
    )
    gateway = RecordingGateway()

    await runtime.observe(event(1, now=clock()))
    runtime.bind_gateway(gateway)
    await runtime.wait_idle()
    assert gateway.calls == []

    await runtime.observe(event(2, now=clock(), critical=True))
    await runtime.wait_idle()
    assert len(gateway.calls) == 1


async def test_trigger_before_model_binding_is_deferred_not_failed() -> None:
    clock = MutableClock()
    runtime = SceneRuntime(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        gateway=None,
        mode="shadow",
        clock=clock,
    )

    await runtime.observe(event(1, now=clock(), critical=True))
    await runtime.wait_idle()
    assert runtime.metrics.reflection_calls == 0
    assert runtime.metrics.reflection_failures == 0

    gateway = RecordingGateway()
    runtime.bind_gateway(gateway)
    await runtime.wait_idle()
    assert len(gateway.calls) == 1
