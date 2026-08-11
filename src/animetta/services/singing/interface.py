from __future__ import annotations

"""Singing service interface and type definitions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


class PipelineStage(StrEnum):
    IDLE = "idle"
    DOWNLOADING = "downloading"
    SEPARATING = "separating"
    TRANSCRIBING = "transcribing"
    WAITING_LYRICS = "waiting_lyrics"
    CONVERTING = "converting"
    MIXING = "mixing"
    DONE = "done"


@dataclass
class LyricLine:
    text: str
    translation: str = ""
    start_ms: int = 0
    end_ms: int = 0


@dataclass
class SongResult:
    audio_path: str
    subtitle_path: str = ""
    tts_audio_path: str = ""
    original_audio_path: str = ""
    vocals_path: str = ""
    duration_sec: float = 0.0
    lyrics: list[LyricLine] = field(default_factory=list)
    video_title: str = ""
    volumes: list[float] = field(default_factory=list)  # lip sync envelope from vocals
    voice_conversion_applied: bool = False
    voice_provider: str = ""
    voice_model: str = ""
    voice_revision: str = ""
    voice_name: str = ""


@dataclass
class PipelineProgress:
    stage: PipelineStage
    progress: float  # 0-100
    message: str = ""


class SingingService(ABC):
    """Abstract base for singing pipeline service."""

    @abstractmethod
    async def process(self, url: str) -> SongResult:
        """Execute full pipeline: download → separate → transcribe → SVC → mix."""
        ...

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel current processing."""
        ...

    @abstractmethod
    async def confirm_lyrics(self, ass_content: str) -> None:
        """Resume pipeline with user-confirmed lyrics."""
        ...

    @abstractmethod
    async def get_progress(self) -> PipelineProgress:
        """Get current pipeline progress."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        ...
