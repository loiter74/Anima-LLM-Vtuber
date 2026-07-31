from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from animetta.services.bilibili import HIGH_HEAT_BURSTS, LivestreamEvent, LivestreamEventType
from evaluations.livestream.dataset import DatasetWriter, HeatTier
from evaluations.livestream.runner import EvaluationRunner


def make_dataset(path: Path) -> None:
    writer = DatasetWriter(path, dataset_id="low-a", heat_tier=HeatTier.LOW)
    writer.write(LivestreamEvent(0, 0, LivestreamEventType.ENTER, "Alice", payload={"user_id": 1}))
    writer.write(
        LivestreamEvent(
            1,
            100,
            LivestreamEventType.DANMAKU,
            "Alice",
            "为什么？",
            {"user_id": 1},
        ),
    )
    writer.finalize(duration_ms=60_000)


@pytest.mark.asyncio
async def test_transport_runner_writes_accounted_evidence_and_conversation(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    output = tmp_path / "artifacts"
    make_dataset(dataset)

    result = await EvaluationRunner(
        dataset,
        output,
        mode="transport",
        speed=1000,
    ).run()

    assert result["hard_gates"]["gates"]["event_accounting"]["passed"] is True
    assert result["reply"]["received"] == 1
    assert result["reply"]["displayed"] == 1
    assert result["reply"]["policy"]["max_replies_per_minute"] == 60
    assert result["lifecycle"]["residual_tasks"] == 0
    assert (output / "evidence.json").is_file()
    records = [
        json.loads(line)
        for line in (output / "conversation.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    assert records[1]["origin"] == "real"
    assert records[1]["admitted"] is True
    assert records[1]["reply_text"].startswith("stub:")
    assert result["origin_results"]["real"]["inputs"] == 2
    assert result["origin_results"]["real"]["reply_success"] == 1
    assert result["hard_gates"]["status"] == "passed"


@pytest.mark.asyncio
async def test_runner_persists_failed_evidence_when_queue_does_not_recover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "dataset"
    output = tmp_path / "artifacts"
    make_dataset(dataset)
    runner = EvaluationRunner(dataset, output, mode="transport", speed=1000)

    async def fail_recovery(*_args: object) -> None:
        raise TimeoutError("reply queue did not recover within 60 seconds")

    monkeypatch.setattr(runner, "_wait_for_callbacks_and_replies", fail_recovery)

    result = await runner.run()

    assert result["hard_gates"]["passed"] is False
    assert result["reply"]["queue_recovered"] is False
    assert result["hard_gates"]["gates"]["burst_recovery"]["passed"] is False
    assert (output / "evidence.json").is_file()
    assert (output / "conversation.jsonl").is_file()


@pytest.mark.asyncio
async def test_runner_rejects_timeline_that_cannot_complete_configured_bursts(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset"
    make_dataset(dataset)

    with pytest.raises(ValueError, match="does not cover configured burst windows"):
        await EvaluationRunner(
            dataset,
            tmp_path / "artifacts",
            mode="transport",
            speed=1,
            burst_windows=HIGH_HEAT_BURSTS,
        ).run()


@pytest.mark.asyncio
async def test_runner_limits_replay_to_configured_source_duration(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    writer = DatasetWriter(dataset, dataset_id="windowed-low", heat_tier=HeatTier.LOW)
    writer.write(
        LivestreamEvent(0, 0, LivestreamEventType.DANMAKU, "Alice", "第一条？", {"user_id": 1})
    )
    writer.write(
        LivestreamEvent(
            1,
            40_000,
            LivestreamEventType.DANMAKU,
            "Bob",
            "窗口外？",
            {"user_id": 2},
        )
    )
    writer.finalize(duration_ms=60_000)

    result = await EvaluationRunner(
        dataset,
        tmp_path / "artifacts",
        mode="transport",
        speed=1000,
        duration_seconds=30,
    ).run()

    assert result["input_events"] == 1
    assert result["source_duration_seconds"] == 30
    assert result["gateway_callback_events"] == 1


def test_runner_rejects_nonpositive_duration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duration_seconds"):
        EvaluationRunner(tmp_path, tmp_path / "out", duration_seconds=0)


@pytest.mark.asyncio
async def test_runner_wait_accepts_admitted_terminal_drops(tmp_path: Path) -> None:
    runner = EvaluationRunner(
        dataset_dir=tmp_path,
        output_dir=tmp_path / "artifacts",
        mode="transport",
    )
    session = SimpleNamespace(
        event_metrics=SimpleNamespace(received=3),
        callback_task_count=0,
    )
    runtime = SimpleNamespace(
        metrics=SimpleNamespace(
            admitted=3,
            reply_success=1,
            reply_failure=0,
            admitted_dropped={"queue_evicted": 2},
            queue_depth=0,
        )
    )

    await runner._wait_for_callbacks_and_replies(session, runtime, 3)


def test_full_runner_requires_injected_production_processor(tmp_path: Path) -> None:
    make_dataset(tmp_path / "dataset")

    with pytest.raises(ValueError, match="reply_processor"):
        EvaluationRunner(tmp_path / "dataset", tmp_path / "out", mode="full")


def test_full_runner_requires_animetta_resource_target(tmp_path: Path) -> None:
    async def processor(_candidate: object) -> str:
        return "ok"

    with pytest.raises(ValueError, match="resource target"):
        EvaluationRunner(
            tmp_path,
            tmp_path / "out",
            mode="full",
            reply_processor=processor,
        )


def test_runner_separates_transport_stress_and_full_production_policies(tmp_path: Path) -> None:
    async def processor(_candidate: object) -> str:
        return "ok"

    transport = EvaluationRunner(tmp_path, tmp_path / "transport")
    full = EvaluationRunner(
        tmp_path,
        tmp_path / "full",
        mode="full",
        reply_processor=processor,
        resource_sampler=lambda: 42.0,
        resource_identity="test:animetta-server",
    )

    transport_policy = transport._policy()
    full_policy = full._policy()

    assert transport_policy.max_replies_per_minute == 60
    assert transport_policy.max_message_age_seconds == 300
    assert transport_policy.ordinary_sample_rate == 1.0
    assert full_policy.max_replies_per_minute == 1
    assert full_policy.max_message_age_seconds == 120
    assert full_policy.per_user_cooldown_seconds == 30
    assert full_policy.duplicate_window_seconds == 60
    assert full_policy.ordinary_sample_rate == 0.1
