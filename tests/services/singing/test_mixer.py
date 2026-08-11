from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from animetta.services.singing.mixer import AudioMixer


async def test_mixer_preserves_stereo_backing_without_amix_attenuation(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout="8.0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", run)
    mixer = AudioMixer(str(tmp_path))

    output = await mixer.mix("vocals.wav", "backing.wav", "final.wav")

    mix_filter = commands[0][commands[0].index("-filter_complex") + 1]
    assert "pan=stereo|c0=c0|c1=c0" in mix_filter
    assert "normalize=0" in mix_filter
    assert "alimiter=limit=0.95:level=false" in mix_filter
    assert commands[0][commands[0].index("-ar") + 1] == "44100"
    assert output == str(tmp_path / "final.wav")
