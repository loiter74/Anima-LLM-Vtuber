"""Tests for singing service interface and lyrics parser."""

from __future__ import annotations

from animetta.services.singing.interface import LyricLine, PipelineStage, SongResult
from animetta.services.singing.lyrics import LyricsGenerator


class TestLyricLine:
    def test_create_basic(self):
        line = LyricLine(text="hello")
        assert line.text == "hello"
        assert line.start_ms == 0
        assert line.end_ms == 0

    def test_create_with_timestamps(self):
        line = LyricLine(text="world", start_ms=1000, end_ms=3000)
        assert line.start_ms == 1000
        assert line.end_ms == 3000


class TestPipelineStage:
    def test_stages_exist(self):
        assert PipelineStage.IDLE == "idle"
        assert PipelineStage.DONE == "done"
        assert PipelineStage.DOWNLOADING == "downloading"


class TestSongResult:
    def test_create_defaults(self):
        result = SongResult(audio_path="/test.wav")
        assert result.audio_path == "/test.wav"
        assert result.lyrics == []
        assert result.duration_sec == 0.0


class TestLyricsGenerator:
    def test_parse_lrc_basic(self):
        lrc = "[00:01.00]Hello\n[00:03.00]World"
        lines = LyricsGenerator.parse_lrc(lrc)
        assert len(lines) == 2
        assert lines[0].text == "Hello"
        assert lines[0].start_ms == 1000
        assert lines[1].text == "World"
        assert lines[1].start_ms == 3000

    def test_parse_lrc_empty(self):
        lines = LyricsGenerator.parse_lrc("")
        assert lines == []

    def test_parse_lrc_end_ms_chain(self):
        lrc = "[00:00.50]A\n[00:01.00]B\n[00:02.00]C"
        lines = LyricsGenerator.parse_lrc(lrc)
        assert lines[0].end_ms == 1000  # ends when B starts
        assert lines[1].end_ms == 2000  # ends when C starts
        assert lines[2].end_ms == 5000  # last line + 3s default

    def test_sec_to_ass_time(self):
        assert LyricsGenerator._sec_to_ass_time(0) == "0:00:00.00"
        assert LyricsGenerator._sec_to_ass_time(61.5) == "0:01:01.50"
        assert LyricsGenerator._sec_to_ass_time(3661.99) == "1:01:01.99"

    def test_ass_time_to_ms(self):
        assert LyricsGenerator._ass_time_to_ms("0:00:01.00") == 1000
        assert LyricsGenerator._ass_time_to_ms("0:01:00.50") == 60500

    def test_parse_lyric_lines(self):
        ass = (
            "[Events]\n"
            "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello world\n"
            "Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,Goodbye\n"
        )
        gen = LyricsGenerator.__new__(LyricsGenerator)
        lines = gen.parse_lyric_lines(ass)
        assert len(lines) == 2
        assert lines[0].text == "Hello world"
        assert lines[0].start_ms == 1000
