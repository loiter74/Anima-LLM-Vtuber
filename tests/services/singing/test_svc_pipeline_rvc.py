from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from animetta.config.singing import SingingConfig
from animetta.services.singing.svc_pipeline import SVCPipeline


def _pipeline(*, required: bool, rvc: object) -> SVCPipeline:
    pipeline = SVCPipeline.__new__(SVCPipeline)
    pipeline.config = SingingConfig(rvc={"enabled": True, "required": required})
    pipeline._rvc = rvc
    pipeline._svc = SimpleNamespace(convert=AsyncMock())
    pipeline._cancelled = False
    pipeline._on_progress = None
    pipeline._stage = None
    pipeline._progress = 0.0
    pipeline._message = ""
    return pipeline


async def test_required_rvc_failure_never_copies_original_vocals(tmp_path: Path) -> None:
    source = tmp_path / "vocals.wav"
    source.write_bytes(b"source vocals")
    output = tmp_path / "converted.wav"
    rvc = SimpleNamespace(
        convert=AsyncMock(side_effect=ConnectionError("host unavailable")),
        last_identity={},
    )

    with pytest.raises(RuntimeError, match="Required RVC voice conversion failed"):
        await _pipeline(required=True, rvc=rvc)._convert_voice(str(source), output)

    assert not output.exists()


async def test_required_rvc_success_returns_auditable_identity(tmp_path: Path) -> None:
    source = tmp_path / "vocals.wav"
    source.write_bytes(b"source vocals")
    output = tmp_path / "converted.wav"

    async def convert(_source: str, target: str) -> None:
        Path(target).write_bytes(b"converted vocals")

    identity = {
        "provider": "rvc-webui-host",
        "model": "shige_utage.pth",
        "revision": "revision",
        "voice": "shige_utage",
    }
    rvc = SimpleNamespace(convert=convert, last_identity=identity)

    applied, actual_identity = await _pipeline(required=True, rvc=rvc)._convert_voice(
        str(source), output
    )

    assert applied is True
    assert actual_identity == identity
    assert output.read_bytes() == b"converted vocals"


def test_lip_sync_uses_isolated_vocals_with_absolute_noise_gate() -> None:
    with patch("animetta.services.singing.svc_pipeline.AudioAnalyzer") as analyzer_type:
        analyzer_type.return_value.compute_volume_envelope.return_value = [0.0, 0.5]

        volumes = SVCPipeline._compute_lip_sync_volumes("isolated-vocals.wav")

    assert volumes == [0.0, 0.5]
    analyzer_type.return_value.compute_volume_envelope.assert_called_once_with(
        "isolated-vocals.wav",
        normalize=True,
        gain=1.8,
        use_peak=False,
        noise_floor=0.025,
    )
