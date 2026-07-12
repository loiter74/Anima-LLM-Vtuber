"""Voyager control-plane state and checkpoint contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts import CapabilityManifest
from animetta.tools.gamebot.runtime import GameBotRuntime


class VoyagerMode(StrEnum):
    STOPPED = "stopped"
    LEARN = "learn"
    LIVE = "live"
    FALLBACK = "fallback"
    RECOVERING = "recovering"


class VoyagerSessionState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class VoyagerStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: VoyagerMode = VoyagerMode.STOPPED
    state: VoyagerSessionState = VoyagerSessionState.STOPPED
    session_id: str = ""
    runtime_id: str = ""
    current_task: str = ""
    unlocked_tech: list[str] = Field(default_factory=list)
    frontier: list[str] = Field(default_factory=list)
    last_failure: str | None = None


class VoyagerCheckpoint(BaseModel):
    """State committed only at a completed task boundary."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    task_id: str
    observation_hash: str
    unlocked_tech: frozenset[str] = frozenset()
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class VoyagerSessionContext:
    session_id: str
    mode: VoyagerMode
    runtime: GameBotRuntime
    manifest: CapabilityManifest
    authorized_capabilities: frozenset[str]
    repository: Any
    goal: str = ""
