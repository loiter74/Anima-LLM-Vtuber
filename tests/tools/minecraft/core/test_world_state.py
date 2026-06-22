from __future__ import annotations

from animetta.tools.minecraft.world_state import WorldState

"""Tests for WorldState model parsing and analysis methods.

Note: Integration-style tests already exist in test_minecraft_autonomous.py.
These tests provide focused unit coverage of edge cases and all analysis methods.
"""

import pytest


def _make_status(overrides: dict = None) -> dict:
    """Helper to create a sample mc_status() result."""
    base = {
        "status": "success",
        "result": {
            "position": {"x": 10.0, "y": 65.0, "z": 10.0},
            "health": 20.0,
            "food": 18.0,
            "dimension": "overworld",
            "game_mode": "survival",
            "weather": "clear",
            "time": "day",
            "biome": "plains",
            "inventory": {"oak_log": 5, "cobblestone": 10},
            "nearby_entities": {"player": 1, "hostile": 0, "neutral": 2, "passive": 4},
            "current_goal": None,
        },
    }
    if overrides:
        # Deep merge
        result = base.copy()
        if "result" in overrides:
            result["result"] = {**base["result"], **overrides["result"]}
        return result
    return base


class TestWorldStateParsing:
    """WorldState.from_status parsing tests."""

    def test_parse_full_status(self):
        state = WorldState.from_status(_make_status())
        assert state.x == 10.0
        assert state.y == 65.0
        assert state.z == 10.0
        assert state.health == 20.0
        assert state.food == 18.0
        assert state.dimension == "overworld"
        assert state.time == "day"
        assert state.weather == "clear"
        assert state.biome == "plains"
        assert state.game_mode == "survival"
        assert state.inventory == {"oak_log": 5, "cobblestone": 10}
        assert state.current_goal is None

    def test_parse_empty_status_returns_defaults(self):
        state = WorldState.from_status({})
        assert state.x == 0.0
        assert state.y == 0.0
        assert state.z == 0.0
        assert state.health == 20.0
        assert state.inventory == {}
        assert len(state.entities) == 0

    def test_parse_status_without_result(self):
        state = WorldState.from_status({"status": "error"})
        assert state.x == 0.0

    def test_parse_none_result(self):
        state = WorldState.from_status({"result": None})
        assert state.x == 0.0

    def test_parse_inventory_not_dict(self):
        state = WorldState.from_status({"result": {"inventory": "not_a_dict"}})
        assert state.inventory == {}

    def test_parse_entities_detailed_format(self):
        status = _make_status({
            "result": {
                "nearby_entities": {
                    "hostile": {"count": 3, "distance": 5.0, "name": "zombie"},
                    "player": {"count": 1, "distance": 10.0, "name": "Player123"},
                }
            }
        })
        state = WorldState.from_status(status)
        assert state.hostile_count == 3
        assert state.player_count == 1
        assert state.nearest_threat_distance == 5.0

    def test_parse_entities_unknown_type_skipped(self):
        status = _make_status({
            "result": {
                "nearby_entities": {"unknown_type": "some_value"}
            }
        })
        state = WorldState.from_status(status)
        assert len(state.entities) == 0


class TestWorldStateProperties:
    """WorldState computed property tests."""

    def test_is_night(self):
        state = WorldState.from_status(_make_status({"result": {"time": "night"}}))
        assert state.is_night is True
        assert state.is_day is False

    def test_is_day(self):
        state = WorldState.from_status(_make_status({"result": {"time": "day"}}))
        assert state.is_day is True
        assert state.is_night is False

    def test_is_sunrise_day(self):
        state = WorldState.from_status(_make_status({"result": {"time": "sunrise"}}))
        assert state.is_day is True

    def test_is_raining(self):
        state = WorldState.from_status(_make_status({"result": {"weather": "rain"}}))
        assert state.is_raining is True

    def test_is_thundering(self):
        state = WorldState.from_status(_make_status({"result": {"weather": "thunder"}}))
        assert state.is_raining is True

    def test_is_not_raining(self):
        state = WorldState.from_status(_make_status())
        assert state.is_raining is False

    def test_is_injured(self):
        state = WorldState.from_status(_make_status({"result": {"health": 5.0}}))
        assert state.is_injured is True

    def test_is_not_injured(self):
        state = WorldState.from_status(_make_status())
        assert state.is_injured is False

    def test_is_hungry(self):
        state = WorldState.from_status(_make_status({"result": {"food": 4.0}}))
        assert state.is_hungry is True

    def test_is_not_hungry(self):
        state = WorldState.from_status(_make_status())
        assert state.is_hungry is False


class TestWorldStateThreatAssessment:
    """Threat level assessment tests."""

    def test_threat_level_0_no_hostiles(self):
        state = WorldState.from_status(_make_status())
        assert state.get_threat_level() == 0

    def test_threat_level_1_few_and_far(self):
        status = _make_status({
            "result": {
                "nearby_entities": {
                    "hostile": {"count": 1, "distance": 20.0, "name": "zombie"}
                },
                "health": 20,
            }
        })
        state = WorldState.from_status(status)
        assert state.get_threat_level() == 1

    def test_threat_level_2_many_hostiles(self):
        status = _make_status({
            "result": {
                "nearby_entities": {"hostile": 3},
                "health": 20,
            }
        })
        state = WorldState.from_status(status)
        assert state.get_threat_level() == 2

    def test_threat_level_2_close_hostile(self):
        status = _make_status({
            "result": {
                "nearby_entities": {
                    "hostile": {"count": 1, "distance": 5.0, "name": "creeper"}
                },
                "health": 20,
            }
        })
        state = WorldState.from_status(status)
        assert state.get_threat_level() == 2

    def test_threat_level_3_low_health_with_hostiles(self):
        status = _make_status({
            "result": {
                "nearby_entities": {"hostile": 1},
                "health": 5.0,
            }
        })
        state = WorldState.from_status(status)
        assert state.get_threat_level() == 3


class TestWorldStateMaterialAnalysis:
    """Material gap analysis tests."""

    def test_get_material_gaps(self):
        state = WorldState.from_status(_make_status())
        gaps = state.get_material_gaps({"oak_log": 10, "cobblestone": 20})
        assert gaps == {"oak_log": 5, "cobblestone": 10}

    def test_get_material_gaps_none_needed(self):
        state = WorldState.from_status(_make_status({"result": {"inventory": {"oak_log": 10}}}))
        gaps = state.get_material_gaps({"oak_log": 10})
        assert gaps == {}

    def test_get_material_gaps_surplus(self):
        state = WorldState.from_status(_make_status({"result": {"inventory": {"oak_log": 20}}}))
        gaps = state.get_material_gaps({"oak_log": 10})
        assert gaps == {}

    def test_has_material_true(self):
        state = WorldState.from_status(_make_status())
        assert state.has_material("oak_log", 5) is True
        assert state.has_material("oak_log", 3) is True

    def test_has_material_false(self):
        state = WorldState.from_status(_make_status())
        assert state.has_material("oak_log", 10) is False
        assert state.has_material("diamond", 1) is False


class TestWorldStateDistance:
    """Distance calculation tests."""

    def test_distance_to(self):
        state = WorldState.from_status(_make_status({"result": {"position": {"x": 0, "y": 0, "z": 0}}}))
        dist = state.distance_to(3.0, 0.0, 4.0)
        assert dist == pytest.approx(5.0)  # 3-4-5 triangle

    def test_distance_to_self(self):
        state = WorldState.from_status(_make_status())
        dist = state.distance_to(10.0, 65.0, 10.0)
        assert dist == pytest.approx(0.0)

    def test_player_nearby_true(self):
        state = WorldState.from_status(_make_status())
        assert state.get_player_nearby() is True

    def test_player_nearby_false(self):
        status = _make_status({"result": {"nearby_entities": {"player": 0}}})
        state = WorldState.from_status(status)
        assert state.get_player_nearby() is False
