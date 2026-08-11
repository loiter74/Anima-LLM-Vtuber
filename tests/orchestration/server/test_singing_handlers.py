"""Singing Socket.IO delivery tests."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.orchestration.server.handlers import singing_handlers
from animetta.orchestration.server.handlers.singing_handlers import SingingHandlers
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
