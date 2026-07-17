"""Immutable domain objects for the blind TTS audition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CandidateProvider(StrEnum):
    """Cloud protocol family used by a candidate."""

    COSYVOICE = "cosyvoice"
    QWEN_REALTIME = "qwen_realtime"


class Emotion(StrEnum):
    """The six existing Animetta speech emotions in stable audition order."""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    THINKING = "thinking"

    @property
    def delivery_modifier(self) -> str:
        """Return the bounded performance change for this emotion."""

        return {
            Emotion.NEUTRAL: "保持自然平稳的语速和轻微停顿",
            Emotion.HAPPY: "只增加轻微明亮感，语速略快，音量略提升",
            Emotion.SAD: "压低音量，放慢语速并增加克制停顿",
            Emotion.ANGRY: "增加坚定力度，语速稍紧，绝不吼叫",
            Emotion.SURPRISED: "首句短暂停顿后略提亮，保持克制",
            Emotion.THINKING: "放慢语速，在关键词前保留思考停顿",
        }[self]


@dataclass(frozen=True, slots=True)
class AuditionCandidate:
    """A provider identity hidden behind an opaque audition label."""

    label: str
    provider: CandidateProvider
    model: str
    voice: str | None
    price_cny_per_10k_chars: float
    voice_design_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class AuditionSample:
    """One candidate/emotion synthesis request."""

    sample_id: str
    candidate_label: str
    emotion: Emotion
    text: str
    instruction: str


@dataclass(frozen=True, slots=True)
class AuditionPlan:
    """Stable candidate identities and their complete blind sample matrix."""

    candidates: tuple[AuditionCandidate, ...]
    samples: tuple[AuditionSample, ...]


@dataclass(frozen=True, slots=True)
class SampleMetrics:
    """Timing, duration, and estimated cost for one generated sample."""

    sample_id: str
    connection_seconds: float
    first_packet_seconds: float
    total_seconds: float
    audio_duration_seconds: float
    rtf: float
    character_count: int
    estimated_cost_cny: float
    cold_connection: bool
    request_id: str | None = None

    @classmethod
    def from_measurement(
        cls,
        *,
        sample_id: str,
        connection_seconds: float,
        first_packet_seconds: float,
        total_seconds: float,
        audio_duration_seconds: float,
        character_count: int,
        price_cny_per_10k_chars: float,
        cold_connection: bool,
        request_id: str | None = None,
    ) -> SampleMetrics:
        """Build derived metrics from raw measurements."""

        if audio_duration_seconds <= 0:
            raise ValueError("audio_duration_seconds must be positive")
        if character_count < 0:
            raise ValueError("character_count must not be negative")
        return cls(
            sample_id=sample_id,
            connection_seconds=connection_seconds,
            first_packet_seconds=first_packet_seconds,
            total_seconds=total_seconds,
            audio_duration_seconds=audio_duration_seconds,
            rtf=total_seconds / audio_duration_seconds,
            character_count=character_count,
            estimated_cost_cny=(character_count / 10_000) * price_cny_per_10k_chars,
            cold_connection=cold_connection,
            request_id=request_id,
        )


@dataclass(frozen=True, slots=True)
class VoiceDesignResult:
    """Created CosyVoice identity plus its reviewable preview audio."""

    voice_id: str
    preview_audio: bytes
    sample_rate: int
    response_format: str
    target_model: str
    request_id: str


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Raw 24 kHz PCM and transport measurements from one synthesis task."""

    audio_pcm: bytes
    request_id: str
    character_count: int
    connection_seconds: float
    first_packet_seconds: float
    total_seconds: float
    cold_connection: bool
