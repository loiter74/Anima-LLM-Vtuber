from __future__ import annotations

from pathlib import Path
from typing import Any

from animetta.services.singing.rvc_bridge import RVCBridge


async def test_remote_rvc_conversion_persists_audio_and_identity(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFFsource")
    output = tmp_path / "converted.wav"
    bridge = RVCBridge(
        base_url="http://host.docker.internal:8769",
        api_key="secret",
        model_name="shige_utage.pth",
        expected_revision="f8e22f8c",
    )

    def request_remote(payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
        assert payload["model"] == "shige_utage.pth"
        assert payload["audio_base64"]
        return b"RIFF" + (b"x" * 64), {
            "x-rvc-provider": "rvc-webui-host",
            "x-rvc-model": "shige_utage.pth",
            "x-rvc-revision": "f8e22f8c",
            "x-rvc-voice": "shige_utage",
        }

    monkeypatch.setattr(bridge, "_request_remote", request_remote)

    actual = await bridge.convert(source, output)

    assert actual == str(output)
    assert output.read_bytes() == b"RIFF" + (b"x" * 64)
    assert bridge.last_identity == {
        "provider": "rvc-webui-host",
        "model": "shige_utage.pth",
        "revision": "f8e22f8c",
        "voice": "shige_utage",
    }


def test_remote_rvc_does_not_require_container_local_windows_assets() -> None:
    bridge = RVCBridge(
        base_url="http://host.docker.internal:8769",
        api_key="secret",
        rvc_path="C:/missing-on-linux",
        model_name="shige_utage.pth",
    )

    assert bridge.availability_problems() == []
