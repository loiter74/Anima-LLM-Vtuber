"""Singing Socket.IO delivery tests."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.orchestration.server.handlers import singing_handlers
from animetta.orchestration.server.handlers.singing_handlers import SingingHandlers
from animetta.services.command_inbox import CommandInbox, CommandKey
from animetta.services.singing.interface import SongResult


async def test_complete_broadcasts_correlated_song_and_closes_pipeline() -> None:
    sio = SimpleNamespace(emit=AsyncMock())
    handler = SingingHandlers(sio, MagicMock(), MagicMock(), MagicMock())
    pipeline = SimpleNamespace(
        process_from_file=AsyncMock(
            return_value=SongResult(
                audio_path="data/singing/outputs/song_final.wav",
                vocals_path="data/singing/outputs/song_vocals.wav",
                original_audio_path="data/singing/outputs/song_original.wav",
                duration_sec=12.0,
                voice_conversion_applied=True,
                voice_provider="rvc-webui-host",
                voice_model="shige_utage.pth",
                voice_revision="revision",
                voice_name="shige_utage",
            )
        ),
        close=AsyncMock(),
    )
    handler._pipeline = pipeline

    await handler._run_pipeline(
        "initiator-sid",
        local_audio="upload.wav",
        auto_confirm=True,
        task_id="sing-task",
        lyrics_text="测试歌词",
    )

    event, payload = sio.emit.await_args.args
    assert event == "sing:complete"
    assert payload["task_id"] == "sing-task"
    assert payload["audio_url"] == "/api/singing/audio/song_final.wav"
    assert payload["voice_conversion_applied"] is True
    assert payload["voice_provider"] == "rvc-webui-host"
    assert payload["voice_model"] == "shige_utage.pth"
    assert "to" not in sio.emit.await_args.kwargs
    pipeline.close.assert_awaited_once()


async def test_uploaded_song_rejects_decoded_audio_over_the_bounded_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = SingingHandlers(
        SimpleNamespace(emit=AsyncMock()), MagicMock(), MagicMock(), MagicMock()
    )
    monkeypatch.setattr(singing_handlers, "MAX_SINGING_UPLOAD_BYTES", 8)

    with pytest.raises(ValueError, match="8 bytes"):
        await handler._save_uploaded_file(
            base64.b64encode(b"123456789").decode("ascii"), "song.wav"
        )


async def test_completed_song_request_replays_without_creating_a_pipeline() -> None:
    sio = SimpleNamespace(emit=AsyncMock())
    inbox = CommandInbox(":memory:")
    handler = SingingHandlers(sio, MagicMock(), MagicMock(), MagicMock(), inbox)
    payload = {
        "task_id": "sing-task",
        "audio_url": "/api/singing/audio/song.wav",
        "duration": 12,
    }
    key = CommandKey("dashboard", "singing.process", "sing-task")
    request = {
        "url": "https://www.bilibili.com/video/BV1",
        "file_sha256": "",
        "file_name": "upload.mp3",
        "local_path": "",
        "auto_confirm": True,
        "lyrics_text": "",
    }
    await inbox.accept(key, request)
    await inbox.mark_processing(key)
    await inbox.succeed(key, payload)

    await handler.on_sing_process(
        "retry-sid",
        {
            "task_id": "sing-task",
            "url": "https://www.bilibili.com/video/BV1",
            "auto_confirm": True,
        },
    )

    sio.emit.assert_awaited_once_with("sing:complete", payload, to="retry-sid")
    assert handler._pipeline is None
    await inbox.close()
