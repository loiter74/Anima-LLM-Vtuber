from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from io import StringIO
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from animetta.acceptance.tts_audition.cli import run_cli
from animetta.acceptance.tts_audition.models import (
    AuditionCandidate,
    SynthesisResult,
    VoiceDesignResult,
)
from animetta.acceptance.tts_audition.runner import run_audition


class FakeCosySession:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def synthesize(
        self,
        *,
        model: str,
        voice: str,
        text: str,
        instruction: str,
    ) -> SynthesisResult:
        self.calls.append(
            {"model": model, "voice": voice, "text": text, "instruction": instruction}
        )
        index = len(self.calls) - 1
        return SynthesisResult(
            audio_pcm=b"\x00\x00" * 4_800,
            request_id=f"cosy-{index}",
            character_count=len(text),
            connection_seconds=0.2 if index == 0 else 0.0,
            first_packet_seconds=1.2,
            total_seconds=1.8,
            cold_connection=index == 0,
        )


class FakeCosyContext(AbstractAsyncContextManager[FakeCosySession]):
    def __init__(self, session: FakeCosySession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeCosySession:
        return self.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None


class FakeCosyClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []
        self.session = FakeCosySession()

    async def create_designed_voice(
        self,
        *,
        candidate: AuditionCandidate,
        prefix: str,
        preview_text: str,
    ) -> VoiceDesignResult:
        self.created.append((candidate.label, prefix, preview_text))
        return VoiceDesignResult(
            voice_id=f"designed-{candidate.label}",
            preview_audio=b"RIFF-preview",
            sample_rate=24_000,
            response_format="wav",
            target_model=candidate.model,
            request_id=f"design-{candidate.label}",
        )

    def open_session(self) -> AbstractAsyncContextManager[FakeCosySession]:
        return FakeCosyContext(self.session)


class FakeQwenClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def synthesize(
        self,
        *,
        model: str,
        voice: str,
        text: str,
        instruction: str,
    ) -> SynthesisResult:
        self.calls.append(
            {"model": model, "voice": voice, "text": text, "instruction": instruction}
        )
        return SynthesisResult(
            audio_pcm=b"\x00\x00" * 4_800,
            request_id=f"qwen-{len(self.calls)}",
            character_count=len(text),
            connection_seconds=0.2,
            first_packet_seconds=1.4,
            total_seconds=2.0,
            cold_connection=True,
        )


async def test_runner_designs_two_voices_and_generates_one_complete_blind_bundle(
    tmp_path: Path,
) -> None:
    cosy = FakeCosyClient()
    qwen = FakeQwenClient()
    progress: list[str] = []

    bundle = await run_audition(
        output_root=tmp_path / "artifacts" / "tts-audition",
        run_id="20260717T120000Z",
        cosy_client=cosy,
        qwen_client=qwen,
        progress=progress.append,
    )

    assert [label for label, _prefix, _preview in cosy.created] == ["A", "B"]
    assert [prefix for _label, prefix, _preview in cosy.created] == ["animaa", "animab"]
    assert len(cosy.session.calls) == 12
    assert len(qwen.calls) == 12
    assert {call["voice"] for call in qwen.calls} == {"Vivian", "Seren"}
    assert len(progress) == 26
    metrics = json.loads((bundle / "metrics.json").read_text(encoding="utf-8"))
    assert len(metrics["samples"]) == 24
    assert metrics["candidates"]["A"]["voice_design_request_id"] == "design-A"
    assert metrics["candidates"]["B"]["voice_design_request_id"] == "design-B"


async def test_runner_leaves_no_local_artifact_when_synthesis_fails(tmp_path: Path) -> None:
    class FailingQwen(FakeQwenClient):
        async def synthesize(self, **kwargs: Any) -> SynthesisResult:
            raise RuntimeError("remote failure")

    output_root = tmp_path / "artifacts" / "tts-audition"

    with pytest.raises(RuntimeError, match="remote failure"):
        await run_audition(
            output_root=output_root,
            run_id="20260717T120000Z",
            cosy_client=FakeCosyClient(),
            qwen_client=FailingQwen(),
        )

    assert not output_root.exists()


def test_cli_requires_python_313_before_executor(tmp_path: Path) -> None:
    calls: list[str] = []
    stderr = StringIO()

    exit_code = run_cli(
        environ={"DASHSCOPE_API_KEY": "secret"},
        output_root=tmp_path,
        execute=lambda _key, _path: calls.append("called"),
        runtime_version=(3, 12),
        stderr=stderr,
    )

    assert exit_code == 2
    assert calls == []
    assert "Python 3.13" in stderr.getvalue()
    assert "secret" not in stderr.getvalue()


def test_cli_sanitizes_unexpected_executor_failure(tmp_path: Path) -> None:
    stderr = StringIO()

    def fail(api_key: str, _output_root: Path) -> None:
        raise RuntimeError(f"transport accidentally contained {api_key}")

    exit_code = run_cli(
        environ={"DASHSCOPE_API_KEY": "super-secret"},
        output_root=tmp_path,
        execute=fail,
        stderr=stderr,
    )

    assert exit_code == 1
    assert "super-secret" not in stderr.getvalue()
    assert "transport accidentally" not in stderr.getvalue()
