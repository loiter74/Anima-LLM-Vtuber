"""Inputs and deterministic outputs for two-pass dialogue services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .contracts import ReasonerResult

CompletedWindow = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ReasonerRequest:
    user_input: str
    persona_prompt: str
    completed_window: CompletedWindow = ()
    roleplay_correction: str = ""


@dataclass(frozen=True, slots=True)
class ComposerRequest:
    user_input: str
    persona_prompt: str
    reasoner: ReasonerResult
    completed_window: CompletedWindow = ()
    mood: Literal["neutral", "bright", "tired", "irritated"] = "neutral"
    fatigue: int = 0
    affinity: int = 50
    roleplay_correction: str = ""


@dataclass(frozen=True, slots=True)
class FinalResponseSelection:
    text: str
    source: Literal["composer", "composer_fallback"]
    rejection_code: str | None = None
