"""Stage-one orchestration for the complete 24-sample audition."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from animetta.acceptance.tts_audition.clients import CosyVoiceClient, QwenRealtimeClient
from animetta.acceptance.tts_audition.evidence import write_evidence_bundle
from animetta.acceptance.tts_audition.models import (
    AuditionCandidate,
    CandidateProvider,
    Emotion,
    SynthesisResult,
    VoiceDesignResult,
)
from animetta.acceptance.tts_audition.plan import build_audition_plan


class CosySessionProtocol(Protocol):
    """Synthesis surface required from a reusable CosyVoice session."""

    async def synthesize(
        self,
        *,
        model: str,
        voice: str,
        text: str,
        instruction: str,
    ) -> SynthesisResult: ...


class CosyClientProtocol(Protocol):
    """Voice design and session surface required by the runner."""

    async def create_designed_voice(
        self,
        *,
        candidate: AuditionCandidate,
        prefix: str,
        preview_text: str,
    ) -> VoiceDesignResult: ...

    def open_session(self) -> AbstractAsyncContextManager[CosySessionProtocol]: ...


class QwenClientProtocol(Protocol):
    """One-shot synthesis surface required from Qwen realtime."""

    async def synthesize(
        self,
        *,
        model: str,
        voice: str,
        text: str,
        instruction: str,
    ) -> SynthesisResult: ...


async def run_audition(
    *,
    output_root: Path,
    run_id: str,
    cosy_client: CosyClientProtocol,
    qwen_client: QwenClientProtocol,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Generate all remote audio in memory, then atomically publish one evidence bundle."""

    report = (lambda _message: None) if progress is None else progress
    plan = build_audition_plan()
    candidates = {candidate.label: candidate for candidate in plan.candidates}
    neutral_text = next(
        sample.text
        for sample in plan.samples
        if sample.candidate_label == "A" and sample.emotion is Emotion.NEUTRAL
    )

    resolved_voices: dict[str, str] = {}
    design_request_ids: dict[str, str] = {}
    for candidate in plan.candidates:
        if candidate.provider is CandidateProvider.COSYVOICE:
            design = await cosy_client.create_designed_voice(
                candidate=candidate,
                prefix=f"anima{candidate.label.lower()}",
                preview_text=neutral_text,
            )
            resolved_voices[candidate.label] = design.voice_id
            design_request_ids[candidate.label] = design.request_id
            report(f"Designed anonymous candidate {candidate.label}")
        else:
            if not candidate.voice:
                raise ValueError(f"candidate {candidate.label} has no preset voice")
            resolved_voices[candidate.label] = candidate.voice

    synthesis_results: dict[str, SynthesisResult] = {}
    async with cosy_client.open_session() as session:
        for sample in plan.samples:
            candidate = candidates[sample.candidate_label]
            if candidate.provider is not CandidateProvider.COSYVOICE:
                continue
            synthesis_results[sample.sample_id] = await session.synthesize(
                model=candidate.model,
                voice=resolved_voices[candidate.label],
                text=sample.text,
                instruction=sample.instruction,
            )
            report(f"Generated {sample.sample_id} ({len(synthesis_results)}/24)")

    for sample in plan.samples:
        candidate = candidates[sample.candidate_label]
        if candidate.provider is not CandidateProvider.QWEN_REALTIME:
            continue
        synthesis_results[sample.sample_id] = await qwen_client.synthesize(
            model=candidate.model,
            voice=resolved_voices[candidate.label],
            text=sample.text,
            instruction=sample.instruction,
        )
        report(f"Generated {sample.sample_id} ({len(synthesis_results)}/24)")

    return write_evidence_bundle(
        output_root=output_root,
        run_id=run_id,
        plan=plan,
        synthesis_results=synthesis_results,
        resolved_voices=resolved_voices,
        design_request_ids=design_request_ids,
    )


def execute_live_audition(api_key: str, output_root: Path) -> Path:
    """Construct live Beijing clients and run the approved stage-one audition."""

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    cosy_client = CosyVoiceClient(api_key=api_key)
    qwen_client = QwenRealtimeClient(api_key=api_key)
    return asyncio.run(
        run_audition(
            output_root=output_root,
            run_id=run_id,
            cosy_client=cosy_client,
            qwen_client=qwen_client,
            progress=print,
        )
    )
