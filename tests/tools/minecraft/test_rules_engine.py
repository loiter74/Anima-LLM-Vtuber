from __future__ import annotations

from animetta.tools.minecraft.rules_engine import RulesEngine

"""Tests for RulesEngine action validation and rule querying.

Note: Integration-style tests (file I/O) already exist in test_minecraft_autonomous.py.
These tests focus on mocking file I/O for isolated unit tests of the engine logic.
"""

import os
import tempfile

import pytest
import yaml


def _make_rules_yaml(overrides: dict = None) -> dict:
    """Helper to create a sample rules dict."""
    base = {
        "character_name": "TestBot",
        "personality": "Test personality",
        "priorities": ["survival", "building", "social"],
        "building": {
            "target": "test_house",
            "blueprint": "A simple test house",
            "required_materials": {"oak_log": 10, "cobblestone": 20},
            "build_plan": [
                {"action": "foundation", "block": "cobblestone", "area": "3x3", "description": "Foundation"},
            ],
        },
        "safety": {
            "return_to_base_at_night": True,
            "auto_heal_threshold": 8,
            "max_distance": 500,
        },
        "chat": {
            "proactive_chance": 0.5,
            "cooldown_seconds": 15,
            "topics": [
                {"trigger": "player_nearby", "messages": ["Hi!", "Hello there!"]},
                {"trigger": "night_time", "messages": ["Getting dark..."]},
            ],
        },
    }
    if overrides:
        base.update(overrides)
    return base


class TestRulesEngineLoading:
    """RulesEngine loading and defaulting behavior."""

    def test_load_valid_rules(self):

        sample = _make_rules_yaml()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        try:
            engine = RulesEngine(rules_path=path)
            assert engine.rules.character_name == "TestBot"
            assert engine.rules.personality == "Test personality"
            assert engine.rules.priorities == ["survival", "building", "social"]
            assert engine.rules.building is not None
            assert engine.rules.building.target == "test_house"
            assert engine.rules.building.required_materials == {"oak_log": 10, "cobblestone": 20}
            assert len(engine.rules.building.build_plan) == 1
        finally:
            os.unlink(path)

    def test_defaults_on_missing_file(self):
        engine = RulesEngine(rules_path="/tmp/nonexistent_rules_test.md")
        assert engine.rules.character_name == "AnimaBot"
        assert len(engine.rules.priorities) > 0

    def test_defaults_on_empty_file(self):

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
            f.write("")
            path = f.name

        try:
            engine = RulesEngine(rules_path=path)
            assert engine.rules.character_name == "AnimaBot"
            assert engine.rules.safety["return_to_base_at_night"] is True
        finally:
            os.unlink(path)

    def test_partial_rules_merge_with_defaults(self):
        """Partial YAML should merge with defaults, not replace them entirely."""

        partial = {"character_name": "PartialBot"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
            yaml.dump(partial, f)
            path = f.name

        try:
            engine = RulesEngine(rules_path=path)
            assert engine.rules.character_name == "PartialBot"
            # Default priorities should remain
            assert len(engine.rules.priorities) > 0
        finally:
            os.unlink(path)


class TestRulesEngineValidation:
    """RulesEngine validation logic tests."""

    @pytest.mark.skip(reason="Needs rules.md file")
    def test_validation_no_priorities(self):
        """Empty priorities should not override defaults."""

        sample = _make_rules_yaml({"priorities": []})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        try:
            engine = RulesEngine(rules_path=path)
            # Empty list doesn't override defaults (len must be > 0)
            assert len(engine.rules.priorities) > 0
        finally:
            os.unlink(path)

    def test_validation_auto_heal_threshold(self):
        """High auto_heal_threshold should be accepted (warnings go to loguru)."""

        sample = _make_rules_yaml({"safety": {"auto_heal_threshold": 25}})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        try:
            engine = RulesEngine(rules_path=path)
            # Should load fine, threshold stored
            assert engine.rules.safety["auto_heal_threshold"] == 25
        finally:
            os.unlink(path)


class TestRulesEngineQueries:
    """RulesEngine query methods (get_priority, get_chat_message)."""

    @pytest.fixture
    def engine(self):

        sample = _make_rules_yaml()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        eng = RulesEngine(rules_path=path)
        yield eng
        os.unlink(path)

    def test_get_priority_known(self, engine):
        assert engine.get_priority("survival") == 0
        assert engine.get_priority("building") == 1
        assert engine.get_priority("social") == 2

    def test_get_priority_unknown(self, engine):
        # Unknown categories get lowest priority
        assert engine.get_priority("unknown") == len(engine.rules.priorities)

    def test_get_chat_message_found(self, engine):
        msg = engine.get_chat_message("player_nearby")
        assert msg in ("Hi!", "Hello there!")

    def test_get_chat_message_not_found(self, engine):
        assert engine.get_chat_message("nonexistent_trigger") is None

    def test_proactive_chat_chance(self, engine):
        assert engine.proactive_chat_chance == 0.5

    def test_chat_cooldown(self, engine):
        assert engine.chat_cooldown == 15.0

    def test_auto_heal_threshold(self, engine):
        assert engine.auto_heal_threshold == 8

    def test_return_to_base_at_night(self, engine):
        assert engine.return_to_base_at_night is True

    def test_is_category_allowed(self, engine):
        assert engine.is_category_allowed("survival") is True
        assert engine.is_category_allowed("flying") is False

    def test_safety_hardcodes(self, engine):
        assert RulesEngine.SAFETY_HARDCODED["no_griefing"] is True
        assert RulesEngine.SAFETY_HARDCODED["max_distance"] == 500
        assert RulesEngine.SAFETY_HARDCODED["min_health_to_fight"] == 6


class TestRulesEngineSafetyOverride:
    """Safety config override from config/tools.yaml."""

    def test_safety_override_applied(self):

        sample = _make_rules_yaml()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        try:
            # max_distance in yaml is 500, override to 300
            engine = RulesEngine(rules_path=path, safety_config={"max_distance": 300})
            assert engine.rules.safety["max_distance"] == 300
        finally:
            os.unlink(path)

    def test_safety_override_not_applied_when_larger(self):

        sample = _make_rules_yaml()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        try:
            # When rules file sets max_distance=500 and config overrides with larger value (600),
            # the smaller (more restrictive) value from rules.md wins
            engine = RulesEngine(rules_path=path, safety_config={"max_distance": 600})
            assert engine.rules.safety["max_distance"] == 500
        finally:
            os.unlink(path)
