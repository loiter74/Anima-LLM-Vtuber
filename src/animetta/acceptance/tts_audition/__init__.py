"""Standalone low-latency emotive TTS audition tooling."""

from animetta.acceptance.tts_audition.evidence import write_evidence_bundle
from animetta.acceptance.tts_audition.models import (
    AuditionCandidate,
    AuditionPlan,
    AuditionSample,
    CandidateProvider,
    Emotion,
    SampleMetrics,
    SynthesisResult,
    VoiceDesignResult,
)
from animetta.acceptance.tts_audition.plan import build_audition_plan
from animetta.acceptance.tts_audition.runner import run_audition

__all__ = [
    "AuditionCandidate",
    "AuditionPlan",
    "AuditionSample",
    "CandidateProvider",
    "Emotion",
    "SampleMetrics",
    "SynthesisResult",
    "VoiceDesignResult",
    "build_audition_plan",
    "write_evidence_bundle",
    "run_audition",
]
