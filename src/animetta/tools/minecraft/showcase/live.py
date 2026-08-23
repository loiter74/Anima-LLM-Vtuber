"""Compatibility facade for the moved Minecraft acceptance showcase."""

from __future__ import annotations

from typing import Any

from animetta.acceptance import minecraft_showcase as _implementation
from animetta.acceptance.minecraft_showcase import (
    ConfiguredModelEvidenceNarrator,
    ConfiguredModelMissionInterpreter,
    DesktopShowcaseCapture,
    EvidenceNarrator,
    InterpretedMission,
    LiveShowcaseBackend,
    MissionSubmitter,
    OrdinaryConversationMissionSubmitter,
    OrdinaryConversationPort,
    ReviewRconSetupExecutor,
    ReviewScenarioEnvironment,
    configured_showcase_llm_from_environment,
    create_ordinary_showcase_submitter,
)


def __getattr__(name: str) -> Any:
    """Preserve private test helpers for the one-release compatibility window."""
    return getattr(_implementation, name)


__all__ = [
    "ConfiguredModelEvidenceNarrator",
    "ConfiguredModelMissionInterpreter",
    "DesktopShowcaseCapture",
    "EvidenceNarrator",
    "InterpretedMission",
    "LiveShowcaseBackend",
    "MissionSubmitter",
    "OrdinaryConversationMissionSubmitter",
    "OrdinaryConversationPort",
    "ReviewRconSetupExecutor",
    "ReviewScenarioEnvironment",
    "configured_showcase_llm_from_environment",
    "create_ordinary_showcase_submitter",
]
