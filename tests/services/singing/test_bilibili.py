from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from animetta.services.singing.bilibili import BilibiliDownloader


class _FFmpegProcess:
    returncode = 0

    def __init__(self, output_path: Path) -> None:
        self._output_path = output_path

    async def communicate(self) -> tuple[bytes, bytes]:
        self._output_path.write_bytes(b"RIFFconverted")
        return b"", b""


async def test_bv_download_uses_official_api_when_yt_dlp_is_blocked(
    monkeypatch: Any, tmp_path: Path
) -> None:
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/x/web-interface/view":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"title": "API song title", "cid": 456},
                },
            )
        if request.url.path == "/x/player/playurl":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "dash": {
                            "audio": [
                                {
                                    "baseUrl": "https://media.bilivideo.com/audio.m4s",
                                    "bandwidth": 192000,
                                }
                            ]
                        }
                    },
                },
            )
        if request.url.host == "media.bilivideo.com":
            return httpx.Response(200, content=b"\x00\x00\x00\x20ftypisom")
        raise AssertionError(f"Unexpected request: {request.url}")

    original_client = httpx.AsyncClient

    def create_client(**kwargs: Any) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(handle_request), **kwargs)

    async def create_subprocess_exec(*command: str, **kwargs: Any) -> _FFmpegProcess:
        assert command[0] == "ffmpeg"
        assert "-i" in command
        assert kwargs["stdout"] is asyncio.subprocess.PIPE
        assert kwargs["stderr"] is asyncio.subprocess.PIPE
        return _FFmpegProcess(Path(command[-1]))

    monkeypatch.setattr(httpx, "AsyncClient", create_client)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    downloader = BilibiliDownloader(str(tmp_path))

    output_path, title, bv_id = await downloader.download(
        "https://www.bilibili.com/video/BV1xF3467Etw"
    )

    assert Path(output_path).read_bytes() == b"RIFFconverted"
    assert title == "API song title"
    assert bv_id == "BV1xF3467Etw"
    assert Path(output_path).with_suffix(".meta").read_text(encoding="utf-8") == title
    assert [request.url.path for request in requests] == [
        "/x/web-interface/view",
        "/x/player/playurl",
        "/audio.m4s",
    ]
    assert requests[-1].headers["referer"].endswith("/video/BV1xF3467Etw")
