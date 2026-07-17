from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError
from io import StringIO
from pathlib import Path

import pytest

from animetta.acceptance.tts_audition.cli import run_cli
from animetta.acceptance.tts_audition.models import Emotion, SampleMetrics
from animetta.acceptance.tts_audition.plan import build_audition_plan


def test_missing_dashscope_key_stops_before_network_or_artifact_creation(tmp_path: Path) -> None:
    output_root = tmp_path / "artifacts" / "tts-audition"
    network_calls: list[str] = []
    stderr = StringIO()

    exit_code = run_cli(
        environ={"QWEN_TTS_API_KEY": "must-not-be-used"},
        output_root=output_root,
        execute=lambda _key, _path: network_calls.append("called"),
        stderr=stderr,
    )

    assert exit_code == 2
    assert network_calls == []
    assert not output_root.exists()
    assert "DASHSCOPE_API_KEY" in stderr.getvalue()
    assert "must-not-be-used" not in stderr.getvalue()


def test_audition_plan_is_a_stable_four_by_six_blind_matrix() -> None:
    first = build_audition_plan()
    second = build_audition_plan()

    assert first == second
    assert tuple(candidate.label for candidate in first.candidates) == ("A", "B", "C", "D")
    assert len(first.samples) == 24
    assert len({sample.sample_id for sample in first.samples}) == 24
    assert Counter(sample.candidate_label for sample in first.samples) == {
        "A": 6,
        "B": 6,
        "C": 6,
        "D": 6,
    }
    assert all(
        {sample.emotion for sample in first.samples if sample.candidate_label == label}
        == set(Emotion)
        for label in ("A", "B", "C", "D")
    )


@pytest.mark.parametrize("emotion", list(Emotion))
def test_every_emotion_instruction_keeps_character_constraints(emotion: Emotion) -> None:
    plan = build_audition_plan()
    instructions = [sample.instruction for sample in plan.samples if sample.emotion is emotion]

    assert len(instructions) == 4
    for instruction in instructions:
        assert "冷静" in instruction
        assert "克制" in instruction
        assert "有教养" in instruction
        assert "不卖萌" in instruction
        assert "不夸张" in instruction
        assert emotion.delivery_modifier in instruction


def test_sample_metrics_are_immutable_and_calculate_rtf_and_cost() -> None:
    metrics = SampleMetrics.from_measurement(
        sample_id="A-neutral",
        connection_seconds=0.25,
        first_packet_seconds=1.5,
        total_seconds=2.4,
        audio_duration_seconds=3.0,
        character_count=25,
        price_cny_per_10k_chars=0.8,
        cold_connection=True,
    )

    assert metrics.rtf == pytest.approx(0.8)
    assert metrics.estimated_cost_cny == pytest.approx(0.002)
    with pytest.raises(FrozenInstanceError):
        metrics.total_seconds = 9.0  # type: ignore[misc]
