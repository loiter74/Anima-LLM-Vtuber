"""Tests for gamebot status snapshot contracts."""

from __future__ import annotations

from animetta.tools.gamebot.contracts.status import (
    GameBotInventoryItem,
    GameBotPosition,
    GameBotStatusSnapshot,
)

# --- Position ---


def test_position_fields() -> None:
    pos = GameBotPosition(x=100.5, y=64.0, z=-200.3)
    assert pos.x == 100.5
    assert pos.y == 64.0
    assert pos.z == -200.3


def test_position_integer_coords() -> None:
    pos = GameBotPosition(x=0, y=0, z=0)
    assert pos.x == 0
    assert pos.y == 0
    assert pos.z == 0


# --- Inventory Item ---


def test_inventory_item_basic() -> None:
    item = GameBotInventoryItem(name="iron_sword", count=1)
    assert item.name == "iron_sword"
    assert item.count == 1
    assert item.slot is None


def test_inventory_item_with_slot() -> None:
    item = GameBotInventoryItem(name="cobblestone", count=64, slot=9)
    assert item.slot == 9


# --- Status Snapshot ---


def test_status_snapshot_full() -> None:
    snap = GameBotStatusSnapshot(
        health=18.5,
        food=15,
        dimension="overworld",
        biome="plains",
        position=GameBotPosition(x=100, y=64, z=-200),
        inventory=[GameBotInventoryItem(name="iron_pickaxe", count=1, slot=0)],
        held_item=GameBotInventoryItem(name="iron_pickaxe", count=1),
        nearby_entities=[{"name": "zombie", "distance": 15.2}],
        nearby_blocks=["stone", "dirt", "grass_block"],
        metadata={"time": "day", "weather": "clear"},
    )
    assert snap.health == 18.5
    assert snap.food == 15
    assert snap.dimension == "overworld"
    assert snap.biome == "plains"
    assert snap.position.x == 100
    assert len(snap.inventory) == 1
    assert snap.held_item.name == "iron_pickaxe"
    assert snap.nearby_entities[0]["name"] == "zombie"
    assert "stone" in snap.nearby_blocks
    assert snap.metadata["time"] == "day"


def test_status_snapshot_minimal() -> None:
    """All fields except position are optional — status response may be partial."""
    snap = GameBotStatusSnapshot()
    assert snap.health is None
    assert snap.food is None
    assert snap.position is None
    assert snap.inventory == []
    assert snap.metadata == {}


def test_status_snapshot_minecraft_metadata() -> None:
    """Minecraft-specific fields go in metadata."""
    snap = GameBotStatusSnapshot(
        health=20.0,
        metadata={
            "dimension": "the_nether",
            "biome": "nether_wastes",
            "time": 18000,
            "weather": "clear",
            "xp_level": 30,
            "armor": 15,
            "effects": ["fire_resistance"],
            "action": "mining",
            "action_target": "nether_gold_ore",
            "held_item": "iron_pickaxe",
        },
    )
    assert snap.metadata["xp_level"] == 30
    assert snap.metadata["effects"] == ["fire_resistance"]
