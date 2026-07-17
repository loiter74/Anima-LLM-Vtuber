"""Atomic evidence bundle and anonymous review page generation."""

from __future__ import annotations

import html
import json
import math
import re
import shutil
import wave
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from animetta.acceptance.tts_audition.models import (
    AuditionPlan,
    SampleMetrics,
    SynthesisResult,
)

SAMPLE_RATE = 24_000
SAMPLE_WIDTH_BYTES = 2
_RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z(?:-[a-z0-9-]+)?$")


def write_evidence_bundle(
    *,
    output_root: Path,
    run_id: str,
    plan: AuditionPlan,
    synthesis_results: Mapping[str, SynthesisResult],
    resolved_voices: Mapping[str, str],
    design_request_ids: Mapping[str, str],
) -> Path:
    """Write a complete bundle to a temporary directory, then publish it atomically."""

    _validate_complete_inputs(
        plan=plan,
        synthesis_results=synthesis_results,
        resolved_voices=resolved_voices,
    )
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must use the safe YYYYMMDDTHHMMSSZ format")
    final_path = output_root / run_id
    temporary_path = output_root / f".{run_id}.tmp"
    if final_path.exists() or temporary_path.exists():
        raise FileExistsError(f"audition bundle already exists for run_id {run_id}")

    root_existed = output_root.exists()
    output_root.mkdir(parents=True, exist_ok=True)
    temporary_path.mkdir()
    try:
        audio_directory = temporary_path / "audio"
        audio_directory.mkdir()
        sample_records = _write_audio_and_sample_metrics(
            audio_directory=audio_directory,
            plan=plan,
            synthesis_results=synthesis_results,
        )
        latency_gate = evaluate_latency_gate(sample_records)
        metrics = {
            "schema_version": 1,
            "status": "complete",
            "run_id": run_id,
            "sample_rate_hz": SAMPLE_RATE,
            "pcm_format": "s16le_mono",
            "candidates": _candidate_manifest(
                plan=plan,
                resolved_voices=resolved_voices,
                design_request_ids=design_request_ids,
            ),
            "samples": sample_records,
            "latency_gate": latency_gate,
            "estimated_total_cost_cny": sum(
                float(record["estimated_cost_cny"]) for record in sample_records
            ),
            "user_review": {
                "status": "pending",
                "minimum_voice_fit_score": 4,
                "minimum_emotion_score": 4,
                "selected_candidate": None,
            },
        }
        _write_text_atomically(
            temporary_path / "metrics.json",
            json.dumps(metrics, ensure_ascii=False, indent=2),
        )
        _write_text_atomically(
            temporary_path / "index.html",
            render_review_page(plan=plan, sample_records=sample_records, latency_gate=latency_gate),
        )
        temporary_path.replace(final_path)
    except Exception:
        if temporary_path.exists():
            shutil.rmtree(temporary_path)
        if not root_existed and output_root.exists() and not any(output_root.iterdir()):
            output_root.rmdir()
        raise
    return final_path


def evaluate_latency_gate(sample_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate the numeric cold and warm first-packet thresholds without picking a voice."""

    cold = [
        float(record["first_packet_seconds"])
        for record in sample_records
        if bool(record["cold_connection"])
    ]
    warm = [
        float(record["first_packet_seconds"])
        for record in sample_records
        if not bool(record["cold_connection"])
    ]
    cold_max = max(cold) if cold else None
    warm_p95 = _nearest_rank_percentile(warm, 95) if warm else None
    return {
        "cold_threshold_seconds": 5.0,
        "warm_p95_threshold_seconds": 3.0,
        "cold_sample_count": len(cold),
        "warm_sample_count": len(warm),
        "cold_first_packet_max_seconds": cold_max,
        "warm_first_packet_p95_seconds": warm_p95,
        "passed": cold_max is not None
        and warm_p95 is not None
        and cold_max <= 5.0
        and warm_p95 <= 3.0,
        "winner_selected": False,
    }


def render_review_page(
    *,
    plan: AuditionPlan,
    sample_records: list[dict[str, Any]],
    latency_gate: Mapping[str, Any],
) -> str:
    """Render a provider-anonymous page with all CSS and JavaScript inline."""

    records = {str(record["sample_id"]): record for record in sample_records}
    sections: list[str] = []
    for candidate in plan.candidates:
        cards = "\n".join(
            _render_sample_card(sample=sample, record=records[sample.sample_id])
            for sample in plan.samples
            if sample.candidate_label == candidate.label
        )
        sections.append(
            f'<section class="candidate"><h2>候选 {candidate.label}</h2><div class="grid">{cards}</div></section>'
        )
    gate_text = "通过" if latency_gate.get("passed") else "未通过"
    warm_p95 = latency_gate.get("warm_first_packet_p95_seconds")
    cold_max = latency_gate.get("cold_first_packet_max_seconds")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Animetta 情绪 TTS 匿名试听</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, "Microsoft YaHei", sans-serif; background: #10131a; color: #edf0f7; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 32px; }}
    main {{ max-width: 1280px; margin: 0 auto; }}
    header, .candidate {{ background: #181d27; border: 1px solid #303848; border-radius: 16px; padding: 24px; margin-bottom: 24px; }}
    h1, h2, h3 {{ margin-top: 0; }}
    .note {{ color: #b6c0d3; line-height: 1.7; }}
    .gate {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }}
    .pill {{ background: #252d3b; border-radius: 999px; padding: 8px 12px; font-variant-numeric: tabular-nums; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
    article {{ background: #202633; border: 1px solid #343d4f; border-radius: 12px; padding: 16px; }}
    .emotion {{ color: #9dc1ff; font-size: 14px; letter-spacing: .04em; text-transform: uppercase; }}
    .text {{ min-height: 72px; line-height: 1.65; }}
    audio {{ width: 100%; margin: 8px 0 14px; }}
    .metrics {{ color: #aeb8ca; font-size: 13px; font-variant-numeric: tabular-nums; }}
    .scores {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }}
    label {{ display: grid; gap: 6px; font-size: 13px; color: #cbd3e2; }}
    select, button {{ border: 1px solid #445067; border-radius: 10px; background: #151a23; color: #edf0f7; padding: 10px; }}
    button {{ cursor: pointer; padding: 12px 18px; font-weight: 650; }}
    footer {{ display: flex; justify-content: flex-end; position: sticky; bottom: 16px; }}
    @media (max-width: 640px) {{ body {{ padding: 16px; }} .scores {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>情绪 TTS 匿名试听</h1>
    <p class="note">请只依据声音本身评分。每段分别评估声线适配与情绪表现；评分完成前不会显示供应商、模型或真实声线身份。播放新样本时，页面会自动暂停上一段。</p>
    <div class="gate">
      <span class="pill">数值延迟门禁：{gate_text}</span>
      <span class="pill">热样本首包 P95：{_format_seconds(warm_p95)}</span>
      <span class="pill">冷样本首包最大值：{_format_seconds(cold_max)}</span>
    </div>
  </header>
  {"".join(sections)}
  <footer><button id="export" type="button">导出评分</button></footer>
</main>
<script>
  const players = Array.from(document.querySelectorAll('audio'));
  players.forEach((player) => player.addEventListener('play', () => {{
    players.forEach((other) => {{ if (other !== player) other.pause(); }});
  }}));
  document.getElementById('export').addEventListener('click', () => {{
    const samples = Array.from(document.querySelectorAll('[data-sample-id]')).map((card) => ({{
      sample_id: card.dataset.sampleId,
      voice_fit: Number(card.querySelector('[data-score="voice"]').value) || null,
      emotion: Number(card.querySelector('[data-score="emotion"]').value) || null
    }}));
    const payload = {{ schema_version: 1, reviewed_at: new Date().toISOString(), samples }};
    const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: 'application/json' }});
    const anchor = document.createElement('a');
    anchor.href = URL.createObjectURL(blob);
    anchor.download = 'anonymous-review.json';
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  }});
</script>
</body>
</html>
"""


def _validate_complete_inputs(
    *,
    plan: AuditionPlan,
    synthesis_results: Mapping[str, SynthesisResult],
    resolved_voices: Mapping[str, str],
) -> None:
    expected_samples = {sample.sample_id for sample in plan.samples}
    expected_candidates = {candidate.label for candidate in plan.candidates}
    if len(plan.samples) != 24 or set(synthesis_results) != expected_samples:
        raise ValueError("evidence bundle requires exactly all 24 planned synthesis results")
    if set(resolved_voices) != expected_candidates or any(
        not voice for voice in resolved_voices.values()
    ):
        raise ValueError("evidence bundle requires one resolved voice for every candidate")


def _write_audio_and_sample_metrics(
    *,
    audio_directory: Path,
    plan: AuditionPlan,
    synthesis_results: Mapping[str, SynthesisResult],
) -> list[dict[str, Any]]:
    candidates = {candidate.label: candidate for candidate in plan.candidates}
    records: list[dict[str, Any]] = []
    for sample in plan.samples:
        result = synthesis_results[sample.sample_id]
        if not result.audio_pcm or len(result.audio_pcm) % SAMPLE_WIDTH_BYTES:
            raise ValueError(f"sample {sample.sample_id} must contain aligned 16-bit PCM")
        audio_path = audio_directory / f"{sample.sample_id}.wav"
        _write_pcm_wav_atomically(audio_path, result.audio_pcm)
        duration = len(result.audio_pcm) / (SAMPLE_RATE * SAMPLE_WIDTH_BYTES)
        candidate = candidates[sample.candidate_label]
        derived = SampleMetrics.from_measurement(
            sample_id=sample.sample_id,
            connection_seconds=result.connection_seconds,
            first_packet_seconds=result.first_packet_seconds,
            total_seconds=result.total_seconds,
            audio_duration_seconds=duration,
            character_count=result.character_count,
            price_cny_per_10k_chars=candidate.price_cny_per_10k_chars,
            cold_connection=result.cold_connection,
            request_id=result.request_id,
        )
        record = asdict(derived)
        record.update(
            {
                "candidate_label": sample.candidate_label,
                "emotion": sample.emotion.value,
                "text": sample.text,
                "instruction": sample.instruction,
                "audio_file": f"audio/{sample.sample_id}.wav",
            }
        )
        records.append(record)
    return records


def _candidate_manifest(
    *,
    plan: AuditionPlan,
    resolved_voices: Mapping[str, str],
    design_request_ids: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    return {
        candidate.label: {
            "provider": candidate.provider.value,
            "model": candidate.model,
            "resolved_voice": resolved_voices[candidate.label],
            "voice_design_prompt": candidate.voice_design_prompt,
            "voice_design_request_id": design_request_ids.get(candidate.label),
            "price_cny_per_10k_chars": candidate.price_cny_per_10k_chars,
        }
        for candidate in plan.candidates
    }


def _render_sample_card(*, sample: Any, record: Mapping[str, Any]) -> str:
    sample_id = html.escape(str(sample.sample_id), quote=True)
    options = '<option value="">未评分</option>' + "".join(
        f'<option value="{score}">{score}</option>' for score in range(1, 6)
    )
    return f"""<article data-sample-id="{sample_id}">
  <div class="emotion">{html.escape(str(sample.emotion.value))}</div>
  <h3>{html.escape(str(sample.candidate_label))} · {html.escape(str(sample.emotion.value))}</h3>
  <p class="text">{html.escape(str(sample.text))}</p>
  <audio controls preload="none" src="audio/{sample_id}.wav"></audio>
  <div class="metrics">首包 {_format_seconds(record["first_packet_seconds"])} · 完整 {_format_seconds(record["total_seconds"])} · RTF {float(record["rtf"]):.2f}</div>
  <div class="scores">
    <label>声线适配<select data-score="voice">{options}</select></label>
    <label>情绪表现<select data-score="emotion">{options}</select></label>
  </div>
</article>"""


def _write_pcm_wav_atomically(path: Path, pcm: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(temporary), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(SAMPLE_WIDTH_BYTES)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(pcm)
    temporary.replace(path)


def _write_text_atomically(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _nearest_rank_percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile / 100 * len(ordered)) - 1)
    return ordered[index]


def _format_seconds(value: Any) -> str:
    return "无数据" if value is None else f"{float(value):.2f}s"
