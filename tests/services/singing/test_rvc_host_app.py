from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from animetta_rvc_host.app import RVCService, RVCServiceSettings, create_app


class FakeEngine:
    def __init__(self) -> None:
        self.preloaded = False
        self.closed = False
        self.payloads: list[bytes] = []

    async def preload(self) -> None:
        self.preloaded = True

    async def convert(self, audio: bytes, **_kwargs: Any) -> bytes:
        self.payloads.append(audio)
        return b"RIFF" + (b"x" * 64)

    async def close(self) -> None:
        self.closed = True


class FakeSeparator:
    model = "htdemucs"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.preloaded = False
        self.closed = False
        self.payloads: list[bytes] = []

    async def preload(self) -> None:
        self.preloaded = True

    async def separate(self, audio: bytes) -> Path:
        self.payloads.append(audio)
        session = self.root / "session"
        session.mkdir()
        archive_path = session / "stems.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("vocals.wav", b"RIFFvocals")
            archive.writestr("backing.wav", b"RIFFbacking")
        return archive_path

    async def close(self) -> None:
        self.closed = True


def test_host_rvc_publishes_identity_and_converted_audio() -> None:
    engine = FakeEngine()
    settings = RVCServiceSettings(
        api_key="secret",
        provider="rvc-webui-host",
        model="shige_utage.pth",
        revision="f8e22f8c",
        voice="shige_utage",
        sample_rate=40000,
    )
    service = RVCService(settings, engine)

    with TestClient(create_app(service)) as client:
        ready = client.get("/ready", headers={"Authorization": "Bearer secret"})
        converted = client.post(
            "/v1/convert",
            headers={"Authorization": "Bearer secret"},
            json={
                "model": "shige_utage.pth",
                "audio_base64": base64.b64encode(b"RIFF" + (b"s" * 64)).decode("ascii"),
                "f0_method": "rmvpe",
            },
        )

    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["revision"] == "f8e22f8c"
    assert converted.status_code == 200
    assert converted.content == b"RIFF" + (b"x" * 64)
    assert converted.headers["x-rvc-model"] == "shige_utage.pth"
    assert converted.headers["x-rvc-revision"] == "f8e22f8c"
    assert engine.payloads == [b"RIFF" + (b"s" * 64)]
    assert engine.closed is True


def test_host_rvc_streams_authenticated_demucs_stems(tmp_path: Path) -> None:
    engine = FakeEngine()
    separator = FakeSeparator(tmp_path)
    settings = RVCServiceSettings(
        api_key="secret",
        provider="rvc-webui-host",
        model="shige_utage.pth",
        revision="f8e22f8c",
        voice="shige_utage",
        sample_rate=40000,
        separation_model="htdemucs",
    )
    service = RVCService(settings, engine, separator)

    with TestClient(create_app(service)) as client:
        ready = client.get("/ready", headers={"Authorization": "Bearer secret"})
        separated = client.post(
            "/v1/separate",
            headers={
                "Authorization": "Bearer secret",
                "Content-Type": "application/octet-stream",
                "X-Separation-Model": "htdemucs",
            },
            content=b"RIFF" + (b"s" * 64),
        )

    assert ready.json()["separation_ready"] is True
    assert ready.json()["separation_model"] == "htdemucs"
    assert separated.status_code == 200
    assert separated.headers["x-separation-model"] == "htdemucs"
    with zipfile.ZipFile(io.BytesIO(separated.content)) as archive:
        assert archive.read("vocals.wav") == b"RIFFvocals"
        assert archive.read("backing.wav") == b"RIFFbacking"
    assert separator.payloads == [b"RIFF" + (b"s" * 64)]
    assert separator.closed is True
