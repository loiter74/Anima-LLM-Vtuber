from __future__ import annotations

import json
import re
import wave
from pathlib import Path

import pytest

from animetta.acceptance.tts_audition.evidence import write_evidence_bundle
from animetta.acceptance.tts_audition.models import SynthesisResult
from animetta.acceptance.tts_audition.plan import build_audition_plan


def _completed_samples() -> dict[str, SynthesisResult]:
    plan = build_audition_plan()
    results: dict[str, SynthesisResult] = {}
    for index, sample in enumerate(plan.samples):
        candidate_index = index // 6
        emotion_index = index % 6
        results[sample.sample_id] = SynthesisResult(
            audio_pcm=b"\x00\x00" * 12_000,
            request_id=f"request-{sample.sample_id}",
            character_count=len(sample.text),
            connection_seconds=0.2 if emotion_index == 0 else 0.0,
            first_packet_seconds=1.2 + candidate_index * 0.1 + emotion_index * 0.05,
            total_seconds=2.0 + emotion_index * 0.05,
            cold_connection=emotion_index == 0,
        )
    return results


def _resolved_voices() -> dict[str, str]:
    return {
        "A": "cosyvoice-v3.5-flash-vd-animaa-secret",
        "B": "cosyvoice-v3.5-flash-vd-animab-secret",
        "C": "Vivian",
        "D": "Seren",
    }


def test_complete_bundle_writes_valid_pcm_wav_and_machine_metrics_atomically(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "artifacts" / "tts-audition"
    plan = build_audition_plan()

    bundle = write_evidence_bundle(
        output_root=output_root,
        run_id="20260717T120000Z",
        plan=plan,
        synthesis_results=_completed_samples(),
        resolved_voices=_resolved_voices(),
        design_request_ids={"A": "design-a", "B": "design-b"},
    )

    assert bundle == output_root / "20260717T120000Z"
    assert not any(path.name.endswith(".tmp") for path in output_root.iterdir())
    audio_files = sorted((bundle / "audio").glob("*.wav"))
    assert len(audio_files) == 24
    with wave.open(str(audio_files[0]), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 24_000
        assert audio.getnframes() == 12_000

    metrics = json.loads((bundle / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["schema_version"] == 1
    assert metrics["status"] == "complete"
    assert len(metrics["samples"]) == 24
    assert metrics["candidates"]["A"]["resolved_voice"] == _resolved_voices()["A"]
    assert metrics["candidates"]["C"]["resolved_voice"] == "Vivian"
    first = metrics["samples"][0]
    assert {
        "connection_seconds",
        "first_packet_seconds",
        "total_seconds",
        "audio_duration_seconds",
        "rtf",
        "character_count",
        "estimated_cost_cny",
        "cold_connection",
    } <= first.keys()
    assert metrics["latency_gate"]["warm_first_packet_p95_seconds"] <= 3.0
    assert metrics["latency_gate"]["cold_first_packet_max_seconds"] <= 5.0
    assert metrics["latency_gate"]["passed"] is True


def test_incomplete_bundle_fails_before_creating_output(tmp_path: Path) -> None:
    output_root = tmp_path / "artifacts" / "tts-audition"
    results = _completed_samples()
    results.pop("D-thinking")

    with pytest.raises(ValueError, match="24"):
        write_evidence_bundle(
            output_root=output_root,
            run_id="20260717T120000Z",
            plan=build_audition_plan(),
            synthesis_results=results,
            resolved_voices=_resolved_voices(),
            design_request_ids={"A": "design-a", "B": "design-b"},
        )

    assert not output_root.exists()


def test_review_page_is_anonymous_self_contained_and_lists_all_samples(tmp_path: Path) -> None:
    bundle = write_evidence_bundle(
        output_root=tmp_path / "artifacts" / "tts-audition",
        run_id="20260717T120000Z",
        plan=build_audition_plan(),
        synthesis_results=_completed_samples(),
        resolved_voices=_resolved_voices(),
        design_request_ids={"A": "design-a", "B": "design-b"},
    )

    page = (bundle / "index.html").read_text(encoding="utf-8")
    lowered = page.lower()
    for hidden_identity in (
        "cosyvoice",
        "qwen",
        "vivian",
        "seren",
        "design-a",
        "design-b",
        "animaa-secret",
    ):
        assert hidden_identity not in lowered
    assert "https://" not in lowered
    assert "http://" not in lowered
    assert "<script src=" not in lowered
    assert "<link " not in lowered
    assert page.count("<audio ") == 24
    assert (
        len(
            re.findall(
                r'data-sample-id="[A-D]-(?:neutral|happy|sad|angry|surprised|thinking)"', page
            )
        )
        == 24
    )
    assert "候选 A" in page
    assert "候选 D" in page
    assert "声线适配" in page
    assert "情绪表现" in page
    assert "导出评分" in page
