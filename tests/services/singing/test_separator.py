from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from animetta.services.singing.separator import HostDemucsSeparator


class _StemResponse(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {"X-Separation-Model": "htdemucs"}


async def test_host_demucs_persists_both_stems(monkeypatch: Any, tmp_path: Path) -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("vocals.wav", b"RIFFvocals")
        archive.writestr("backing.wav", b"RIFFbacking")

    def urlopen(request: Any, timeout: float) -> _StemResponse:
        assert request.full_url == "http://host.docker.internal:8769/v1/separate"
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.headers["X-separation-model"] == "htdemucs"
        assert request.data == b"RIFF" + (b"s" * 64)
        assert timeout == 1200.0
        return _StemResponse(archive_buffer.getvalue())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF" + (b"s" * 64))
    separator = HostDemucsSeparator(
        model="htdemucs",
        output_dir=str(tmp_path / "separated"),
        base_url="http://host.docker.internal:8769",
        api_key="secret",
        request_timeout_seconds=1200.0,
    )

    vocals, backing = await separator.separate(str(source))

    assert Path(vocals).read_bytes() == b"RIFFvocals"
    assert Path(backing).read_bytes() == b"RIFFbacking"
