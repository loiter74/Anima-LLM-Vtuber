"""Gamebot status snapshot contracts — generic game state representation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GameBotPosition(BaseModel):
    """3D position in the game world."""

    x: float
    y: float
    z: float


class GameBotInventoryItem(BaseModel):
    """An item in the bot's inventory."""

    name: str
    count: int
    slot: int | None = None


class GameBotStatusSnapshot(BaseModel):
    """A generic game bot status snapshot.

    Fields are ordered by how commonly the existing HUD uses them.
    Minecraft-specific fields that don't fit the generic model
    should be carried in `metadata`.
    """

    health: float | None = None
    food: int | None = None
    dimension: str | None = None
    biome: str | None = None
    position: GameBotPosition | None = None
    inventory: list[GameBotInventoryItem] = Field(default_factory=list)
    held_item: GameBotInventoryItem | None = None
    nearby_entities: list[dict[str, Any]] = Field(default_factory=list)
    nearby_blocks: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
