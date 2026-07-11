import io
import math
import struct
import wave
from types import SimpleNamespace

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
        model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        preload_status={"state": "ready"},
    )
    evidence = build_evidence(wav_bytes(), provider, "task-id")
    assert evidence["ok"] is True
    assert evidence["audio_bytes"] > 44
    assert evidence["volume_nonzero"] > 0
    assert evidence["live2d"]["task_id"] == "task-id"
    assert evidence["provider"]["voice"] == "alice_vc"
