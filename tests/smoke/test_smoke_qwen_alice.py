import builtins
import io
import math
import runpy
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.smoke_qwen_alice import build_evidence


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        samples = [int(8000 * math.sin(index / 10)) for index in range(2400)]
        target.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
    return output.getvalue()


def test_smoke_evidence_requires_audio_envelope_and_live2d_correlation() -> None:
    provider = SimpleNamespace(
        provider="qwen3",
        model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        voice="alice",
        resolved_identity={
            "provider": "qwen3",
            "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            "voice": "alice",
        },
    )
    evidence = build_evidence(wav_bytes(), provider, "task-id")
    assert evidence["ok"] is True
    assert evidence["audio_bytes"] > 44
    assert evidence["volume_nonzero"] > 0
    assert evidence["live2d"]["task_id"] == "task-id"
    assert evidence["provider"]["voice"] == "alice"


def test_smoke_evidence_rejects_a_structurally_valid_but_silent_wav() -> None:
    provider = SimpleNamespace(
        provider="qwen3",
        model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        voice="alice",
        resolved_identity={
            "provider": "qwen3",
            "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            "voice": "alice",
            "revision": "5d83992436eae1d760afd27aff78a71d676296fc",
        },
    )
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(b"\x00\x00" * 2400)

    evidence = build_evidence(output.getvalue(), provider, "silent-task")

    assert evidence["volume_samples"] > 0
    assert evidence["volume_nonzero"] == 0
    assert evidence["ok"] is False


def test_smoke_module_loads_when_audioop_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def import_without_audioop(name: str, *args: object, **kwargs: object) -> object:
        if name == "audioop":
            raise ModuleNotFoundError("No module named 'audioop'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_audioop)
    namespace = runpy.run_path(
        str(Path(__file__).parents[2] / "scripts" / "smoke_qwen_alice.py"),
        run_name="smoke_qwen_alice_without_audioop",
    )

    assert namespace["_wav_volumes"](wav_bytes())
