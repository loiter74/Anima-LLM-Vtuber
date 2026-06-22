from __future__ import annotations

"""Tests for PresetLoader YAML loading and action creation."""

import os
import tempfile

import pytest
import yaml

from animetta.services.live2d.preset_loader import PresetLoader, get_preset_loader


def _make_sample_presets() -> dict:
    """Create a sample presets dictionary."""
    return {
        "emote": {
            "happy": {
                "low": {"expression": "smile", "params": [{"name": "ParamMouthOpen", "value": 0.3}]},
                "medium": {"expression": "smile", "params": [{"name": "ParamMouthOpen", "value": 0.5}]},
                "high": {"expression": "big_smile", "params": [{"name": "ParamMouthOpen", "value": 0.8}]},
            },
            "sad": {
                "medium": {"expression": "frown", "params": [{"name": "ParamMouthOpen", "value": 0.1}]},
            },
        },
        "gesture": {
            "greet": {
                "expression": "smile",
                "motion": {"group": "greeting", "index": 0},
            },
            "think": {
                "expression": "neutral",
                "motion": {"group": "thinking", "index": 0},
            },
        },
        "react": {
            "success": [
                {"type": "expression", "name": "happy"},
                {"type": "wait", "ms": 500},
                {"type": "motion", "group": "pose", "index": 1},
            ],
            "error": [
                {"type": "expression", "name": "angry"},
                {"type": "wait", "ms": 300},
            ],
        },
    }


class TestPresetLoaderLoading:
    """PresetLoader YAML loading tests."""

    def test_load_valid_yaml(self):

        sample = _make_sample_presets()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        try:
            loader = PresetLoader(config_path=path)
            assert "emote" in loader.presets
            assert "gesture" in loader.presets
            assert "react" in loader.presets
        finally:
            os.unlink(path)

    def test_load_nonexistent_file(self):
        loader = PresetLoader(config_path="/tmp/nonexistent_presets.yaml")
        assert loader.presets == {}

    def test_load_invalid_yaml(self):

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8", delete=False) as f:
            f.write("::: invalid yaml :::")
            path = f.name

        try:
            loader = PresetLoader(config_path=path)
            assert loader.presets == {}
        finally:
            os.unlink(path)


class TestPresetLoaderQueries:
    """Preset data query methods."""

    @pytest.fixture
    def loader(self):

        sample = _make_sample_presets()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        ld = PresetLoader(config_path=path)
        yield ld
        os.unlink(path)

    def test_get_emote_found(self, loader):
        preset = loader.get_emote("happy", "medium")
        assert preset is not None
        assert preset["expression"] == "smile"

    def test_get_emote_not_found(self, loader):
        preset = loader.get_emote("nonexistent", "medium")
        assert preset is None

    def test_get_emote_fallback_to_medium(self, loader):
        # "happy" has no "low" intensity defined... actually it does in our fixture
        # Let me test with an emotion that only has "medium"
        preset = loader.get_emote("sad")  # no intensity specified
        assert preset is not None
        assert preset["expression"] == "frown"

    def test_get_gesture_found(self, loader):
        preset = loader.get_gesture("greet")
        assert preset is not None
        assert preset["motion"]["group"] == "greeting"

    def test_get_gesture_not_found(self, loader):
        preset = loader.get_gesture("nonexistent")
        assert preset is None

    def test_get_react_found(self, loader):
        preset = loader.get_react("success")
        assert preset is not None
        assert len(preset) == 3

    def test_get_react_not_found(self, loader):
        preset = loader.get_react("nonexistent")
        assert preset is None

    def test_list_emotes(self, loader):
        emotes = loader.list_emotes()
        assert "happy" in emotes
        assert "sad" in emotes

    def test_list_gestures(self, loader):
        gestures = loader.list_gestures()
        assert "greet" in gestures
        assert "think" in gestures

    def test_list_reacts(self, loader):
        reacts = loader.list_reacts()
        assert "success" in reacts
        assert "error" in reacts


class TestPresetLoaderCreateActions:
    """Action creation from presets."""

    @pytest.fixture
    def loader(self):

        sample = _make_sample_presets()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8", delete=False) as f:
            yaml.dump(sample, f)
            path = f.name

        ld = PresetLoader(config_path=path)
        yield ld
        os.unlink(path)

    def test_create_emote_action_multi_as_sequence(self, loader):
        """When emote has expression + params, wrap in sequence."""
        action = loader.create_emote_action("happy", "low")
        assert action is not None
        # expression + params = 2 actions -> should be a sequence
        assert action.action["type"] == "sequence"

    def test_create_emote_action_single_action_via_custom_preset(self):
        """When emote has only one action, return a simple ActionMessage."""
        import os
        import tempfile

        import yaml

        # Create a preset with expression-only (no params)
        presets = {
            "emote": {
                "wave": {
                    "medium": {"expression": "wave_hand"},
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8", delete=False) as f:
            yaml.dump(presets, f)
            path = f.name
        try:
            loader = PresetLoader(config_path=path)
            action = loader.create_emote_action("wave", "medium")
            assert action is not None
            assert action.action["type"] == "expression"
        finally:
            os.unlink(path)

    def test_create_emote_action_not_found(self, loader):
        action = loader.create_emote_action("nonexistent", "medium")
        assert action is None

    def test_create_gesture_action(self, loader):
        action = loader.create_gesture_action("greet")
        assert action is not None
        # gesture with expression + motion -> sequence
        assert action.action["type"] == "sequence"

    def test_create_gesture_action_not_found(self, loader):
        action = loader.create_gesture_action("nonexistent")
        assert action is None

    def test_create_react_action(self, loader):
        action = loader.create_react_action("success")
        assert action is not None
        assert "react" in action.action_id
        assert action.action["type"] == "sequence"
        assert len(action.action["actions"]) == 3
        assert action.duration_sec > 0  # has a wait action

    def test_create_react_action_not_found(self, loader):
        action = loader.create_react_action("nonexistent")
        assert action is None


class TestPresetLoaderGlobalInstance:
    """Global preset loader singleton."""

    def test_get_preset_loader(self):
        loader = get_preset_loader()
        assert loader is not None
        assert hasattr(loader, "get_emote")

    def test_get_preset_loader_is_singleton(self):
        loader1 = get_preset_loader()
        loader2 = get_preset_loader()
        assert loader1 is loader2
