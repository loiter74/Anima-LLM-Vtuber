"""Smoke tests for the singing pipeline — module loading, configs, data types.

These tests verify that the singing module can be imported and its core
data structures work correctly. They do NOT run the full pipeline (no
network, no model loading, no heavy computation).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

# ── Module imports ──────────────────────────────────────────────────


def test_singing_module_imports():
    """All core singing types should be importable."""
    from animetta.services.singing import (
        SingingService,
        SVCPipeline,
    )

    assert SVCPipeline is not None
    assert SingingService is not None


def test_config_module_imports():
    """Singing config models should be importable."""
    from animetta.config.singing import (
        RVCConfig,
        SingingConfig,
    )

    assert SingingConfig is not None
    assert RVCConfig is not None


# ── Data types ──────────────────────────────────────────────────────


def test_pipeline_stage_enum():
    """PipelineStage enum should have all expected values."""
    from animetta.services.singing import PipelineStage

    stages = {s.value for s in PipelineStage}
    expected = {
        "idle",
        "downloading",
        "separating",
        "transcribing",
        "waiting_lyrics",
        "converting",
        "mixing",
        "done",
    }
    assert stages == expected


def test_lyric_line_defaults():
    """LyricLine dataclass should have sensible defaults."""
    from animetta.services.singing import LyricLine

    line = LyricLine(text="hello")
    assert line.text == "hello"
    assert line.translation == ""
    assert line.start_ms == 0
    assert line.end_ms == 0


def test_song_result_creation():
    """SongResult should accept keyword arguments."""
    from animetta.services.singing import LyricLine, SongResult

    result = SongResult(
        audio_path="/tmp/output.wav",
        duration_sec=120.5,
        lyrics=[LyricLine(text="la la la", start_ms=0, end_ms=3000)],
        video_title="Test Song",
    )
    assert result.audio_path == "/tmp/output.wav"
    assert result.duration_sec == 120.5
    assert len(result.lyrics) == 1
    assert result.video_title == "Test Song"
    assert result.subtitle_path == ""  # default
    assert result.volumes == []  # default


def test_pipeline_progress_creation():
    """PipelineProgress should track stage + percentage."""
    from animetta.services.singing import PipelineProgress, PipelineStage

    p = PipelineProgress(
        stage=PipelineStage.DOWNLOADING, progress=45.0, message="Fetching audio..."
    )
    assert p.stage == PipelineStage.DOWNLOADING
    assert p.progress == 45.0
    assert p.message == "Fetching audio..."


# ── Config defaults ─────────────────────────────────────────────────


def test_singing_config_defaults():
    """SingingConfig should instantiate with all defaults."""
    from animetta.config.singing import SingingConfig

    cfg = SingingConfig()
    assert cfg.rvc.enabled is False
    assert cfg.separation.engine == "demucs"
    assert cfg.separation.fallback_engine == "ffmpeg"
    assert cfg.gpt_sovits.base_url == "http://127.0.0.1:9880"


def test_repository_singing_playlist_is_ordered_and_unique():
    from animetta.config.singing import load_singing_config

    playlist = load_singing_config().playlist

    assert len(playlist) == 8
    assert [entry.role for entry in playlist] == [
        "开场",
        "热场",
        "主打",
        "互动",
        "推进",
        "高潮",
        "舞台",
        "收尾",
    ]
    assert len({entry.id for entry in playlist}) == len(playlist)


def test_rvc_config_disabled_by_default():
    """RVC should be opt-in only."""
    from animetta.config.singing import RVCConfig

    cfg = RVCConfig()
    assert cfg.enabled is False


def test_singing_config_can_disable_rvc():
    """RVC can be toggled off — needed for smoke-test-safe instantiation."""
    from animetta.config.singing import SingingConfig

    cfg = SingingConfig(rvc={"enabled": False})
    assert cfg.rvc.enabled is False


def test_rvc_config_expands_environment_path(monkeypatch):
    from animetta.config.singing import RVCConfig

    monkeypatch.setenv("ANIMETTA_TEST_RVC_PATH", "C:/models/rvc")

    cfg = RVCConfig(rvc_path="${ANIMETTA_TEST_RVC_PATH:}")

    assert cfg.rvc_path == "C:/models/rvc"


def test_rvc_host_config_expands_url_and_requires_positive_timeout(monkeypatch):
    """The Docker-facing host service stays configurable without weakening identity."""
    from animetta.config.singing import RVCConfig

    monkeypatch.setenv("ANIMETTA_TEST_RVC_URL", "http://host.docker.internal:8769")
    cfg = RVCConfig(
        enabled=True,
        required=True,
        base_url="${ANIMETTA_TEST_RVC_URL:}",
        expected_revision="revision",
    )

    assert cfg.base_url == "http://host.docker.internal:8769"
    assert cfg.required is True
    assert cfg.api_key_env == "QWEN_TTS_API_KEY"
    with pytest.raises(ValidationError):
        RVCConfig(request_timeout_seconds=0)


# ── Real audio fixture ──────────────────────────────────────────────


def test_real_singing_fixture_exists():
    """The smoke test audio fixture (Bilibili BV14oEA6iECF) should exist."""
    fixture = Path(__file__).parent.parent / "fixtures" / "audio" / "singing_test.m4a"
    assert fixture.exists(), f"Fixture missing: {fixture}"
    assert fixture.stat().st_size > 100_000, "Fixture too small — re-download"


def test_real_singing_fixture_is_valid_audio():
    """The fixture should be a valid M4A container (magic bytes check)."""
    fixture = Path(__file__).parent.parent / "fixtures" / "audio" / "singing_test.m4a"
    # M4A/MP4 starts with ftyp box
    with open(fixture, "rb") as f:
        header = f.read(12)
    # ftyp box: 4 bytes size + b'ftyp' + 4 bytes brand
    assert header[4:8] == b"ftyp", f"Not a valid MP4/M4A: {header.hex()}"
