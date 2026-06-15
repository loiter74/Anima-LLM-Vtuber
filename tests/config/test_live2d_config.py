from __future__ import annotations

from animetta.config.live2d import (
    Live2DConfig,
    Live2DLipSyncConfig,
    Live2DModelConfig,
    get_live2d_config,
    reset_live2d_config,
)

"""Tests for Live2D config (config/live2d.py)"""

import sys
from pathlib import Path
from unittest.mock import mock_open, patch

# Ensure src/ is on the Python path
_src_path = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)



# ═══════════════════════════════════════════════════════════════
# Sample YAML data for testing
# ═══════════════════════════════════════════════════════════════

SAMPLE_LIVE2D_YAML = """
enabled: true
model:
  path: "/custom/live2d/model.model3.json"
  scale: 0.8
  position:
    x: 100
    y: 50
emotion_map:
  happy: 5
  sad: 2
  angry: 3
valid_emotions:
  - happy
  - sad
  - angry
lip_sync:
  enabled: true
  sensitivity: 1.5
  smoothing: 0.3
prompt_template_path: "custom/prompts/live2d.txt"
"""

# Pre-parsed data to avoid conflict with mocked yaml.safe_load in tests
_PARSED_LIVE2D_DATA = {
    "enabled": True,
    "model": {
        "path": "/custom/live2d/model.model3.json",
        "scale": 0.8,
        "position": {"x": 100, "y": 50},
    },
    "emotion_map": {"happy": 5, "sad": 2, "angry": 3},
    "valid_emotions": ["happy", "sad", "angry"],
    "lip_sync": {"enabled": True, "sensitivity": 1.5, "smoothing": 0.3},
    "prompt_template_path": "custom/prompts/live2d.txt",
}


# ═══════════════════════════════════════════════════════════════
# Test Live2DModelConfig
# ═══════════════════════════════════════════════════════════════

class TestLive2DModelConfig:
    """Tests for Live2DModelConfig"""

    def test_default_path(self):
        config = Live2DModelConfig()
        assert config.path == "/live2d/haru/haru_greeter_t03.model3.json"

    def test_default_scale(self):
        config = Live2DModelConfig()
        assert config.scale == 0.5

    def test_default_position(self):
        config = Live2DModelConfig()
        assert config.position == {"x": 0, "y": 0}

    def test_custom_values(self):
        config = Live2DModelConfig(
            path="/custom/model.model3.json",
            scale=1.0,
            position={"x": 200, "y": 100},
        )
        assert config.path == "/custom/model.model3.json"
        assert config.scale == 1.0
        assert config.position == {"x": 200, "y": 100}


# ═══════════════════════════════════════════════════════════════
# Test Live2DLipSyncConfig
# ═══════════════════════════════════════════════════════════════

class TestLive2DLipSyncConfig:
    """Tests for Live2DLipSyncConfig"""

    def test_default_enabled(self):
        config = Live2DLipSyncConfig()
        assert config.enabled is True

    def test_default_sensitivity(self):
        config = Live2DLipSyncConfig()
        assert config.sensitivity == 1.0

    def test_default_smoothing(self):
        config = Live2DLipSyncConfig()
        assert config.smoothing == 0.5

    def test_sensitivity_range(self):
        """sensitivity must be between 0.0 and 2.0"""
        config = Live2DLipSyncConfig(sensitivity=0.0)
        assert config.sensitivity == 0.0
        config = Live2DLipSyncConfig(sensitivity=2.0)
        assert config.sensitivity == 2.0

    def test_smoothing_range(self):
        """smoothing must be between 0.0 and 1.0"""
        config = Live2DLipSyncConfig(smoothing=0.0)
        assert config.smoothing == 0.0
        config = Live2DLipSyncConfig(smoothing=1.0)
        assert config.smoothing == 1.0

    def test_custom_values(self):
        config = Live2DLipSyncConfig(
            enabled=False,
            sensitivity=1.8,
            smoothing=0.2,
        )
        assert config.enabled is False
        assert config.sensitivity == 1.8
        assert config.smoothing == 0.2

    def test_disabled_lip_sync(self):
        config = Live2DLipSyncConfig(enabled=False)
        assert config.enabled is False


# ═══════════════════════════════════════════════════════════════
# Test Live2DConfig
# ═══════════════════════════════════════════════════════════════

class TestLive2DConfigDefaults:
    """Tests for Live2DConfig default values"""

    def test_default_enabled(self):
        config = Live2DConfig()
        assert config.enabled is True

    def test_default_model_is_live2d_model_config_instance(self):
        config = Live2DConfig()
        assert isinstance(config.model, Live2DModelConfig)
        assert config.model.scale == 0.5

    def test_default_emotion_map_has_six_emotions(self):
        config = Live2DConfig()
        assert len(config.emotion_map) == 6
        assert config.emotion_map["happy"] == 3
        assert config.emotion_map["sad"] == 1
        assert config.emotion_map["angry"] == 2
        assert config.emotion_map["surprised"] == 4
        assert config.emotion_map["neutral"] == 0
        assert config.emotion_map["thinking"] == 5

    def test_default_valid_emotions(self):
        config = Live2DConfig()
        assert config.valid_emotions == [
            "happy", "sad", "angry", "surprised", "neutral", "thinking",
        ]

    def test_default_lip_sync(self):
        config = Live2DConfig()
        assert isinstance(config.lip_sync, Live2DLipSyncConfig)
        assert config.lip_sync.enabled is True
        assert config.lip_sync.sensitivity == 1.0

    def test_default_prompt_template_path(self):
        config = Live2DConfig()
        assert config.prompt_template_path == "config/prompts/live2d_expression.txt"


class TestLive2DConfigEmotionMethods:
    """Tests for Live2DConfig emotion query methods"""

    def test_get_emotion_names_returns_keys(self):
        config = Live2DConfig()
        names = config.get_emotion_names()
        assert sorted(names) == sorted(["happy", "sad", "angry", "surprised", "neutral", "thinking"])

    def test_get_motion_index_returns_correct_value(self):
        config = Live2DConfig()
        assert config.get_motion_index("happy") == 3
        assert config.get_motion_index("sad") == 1
        assert config.get_motion_index("neutral") == 0

    def test_get_motion_index_returns_none_for_unknown(self):
        config = Live2DConfig()
        assert config.get_motion_index("unknown_emotion") is None

    def test_is_valid_emotion_returns_true(self):
        config = Live2DConfig()
        assert config.is_valid_emotion("happy") is True
        assert config.is_valid_emotion("neutral") is True

    def test_is_valid_emotion_returns_false(self):
        config = Live2DConfig()
        assert config.is_valid_emotion("nonexistent") is False

    def test_is_valid_emotion_uses_emotion_map(self):
        """is_valid_emotion checks against emotion_map (not valid_emotions list)"""
        config = Live2DConfig(emotion_map={"custom": 10})
        assert config.is_valid_emotion("custom") is True
        assert config.is_valid_emotion("happy") is False


class TestLive2DConfigCustomConfig:
    """Tests for Live2DConfig with custom values"""

    def test_disabled_config(self):
        config = Live2DConfig(enabled=False)
        assert config.enabled is False

    def test_custom_emotion_map(self):
        config = Live2DConfig(emotion_map={"love": 10, "hate": 20})
        assert config.emotion_map == {"love": 10, "hate": 20}
        assert config.is_valid_emotion("love") is True

    def test_custom_model_config(self):
        config = Live2DConfig(
            model=Live2DModelConfig(path="/custom/model.json", scale=2.0),
        )
        assert config.model.path == "/custom/model.json"
        assert config.model.scale == 2.0

    def test_custom_lip_sync(self):
        config = Live2DConfig(
            lip_sync=Live2DLipSyncConfig(enabled=False, sensitivity=0.5),
        )
        assert config.lip_sync.enabled is False
        assert config.lip_sync.sensitivity == 0.5


# ═══════════════════════════════════════════════════════════════
# Test Live2DConfig.from_yaml
# ═══════════════════════════════════════════════════════════════

class TestFromYaml:
    """Tests for Live2DConfig.from_yaml"""

    @patch("yaml.safe_load")
    @patch("builtins.open", new_callable=mock_open, read_data="dummy")
    @patch("pathlib.Path.exists", return_value=True)
    def test_loads_from_yaml_file(self, mock_exists, mock_file, mock_yaml_load):
        """from_yaml loads YAML data into Live2DConfig"""
        mock_yaml_load.return_value = {
            "enabled": False,
            "emotion_map": {"happy": 10},
        }
        config = Live2DConfig.from_yaml("/fake/live2d.yaml")

        assert config.enabled is False
        assert config.emotion_map == {"happy": 10}

    @patch("yaml.safe_load")
    @patch("builtins.open", new_callable=mock_open, read_data="dummy")
    @patch("pathlib.Path.exists", return_value=True)
    def test_loads_with_all_nested_models(self, mock_exists, mock_file, mock_yaml_load):
        """from_yaml properly constructs all nested models from YAML"""
        mock_yaml_load.return_value = _PARSED_LIVE2D_DATA

        config = Live2DConfig.from_yaml("/fake/live2d.yaml")

        assert config.enabled is True
        assert isinstance(config.model, Live2DModelConfig)
        assert config.model.path == "/custom/live2d/model.model3.json"
        assert config.model.scale == 0.8
        assert config.model.position == {"x": 100, "y": 50}
        assert config.emotion_map == {"happy": 5, "sad": 2, "angry": 3}
        assert config.valid_emotions == ["happy", "sad", "angry"]
        assert isinstance(config.lip_sync, Live2DLipSyncConfig)
        assert config.lip_sync.enabled is True
        assert config.lip_sync.sensitivity == 1.5
        assert config.lip_sync.smoothing == 0.3
        assert config.prompt_template_path == "custom/prompts/live2d.txt"

    @patch("pathlib.Path.exists", return_value=False)
    def test_returns_default_when_file_not_found(self, mock_exists):
        """from_yaml returns default Live2DConfig when file doesn't exist"""
        config = Live2DConfig.from_yaml("/nonexistent/live2d.yaml")
        assert isinstance(config, Live2DConfig)
        assert config.enabled is True
        assert config.emotion_map["neutral"] == 0

    @patch("yaml.safe_load", return_value={})
    @patch("builtins.open", new_callable=mock_open, read_data="")
    @patch("pathlib.Path.exists", return_value=True)
    def test_handles_empty_yaml(self, mock_exists, mock_file, mock_yaml_load):
        """from_yaml handles empty YAML file (returns defaults)"""
        config = Live2DConfig.from_yaml("/fake/live2d.yaml")
        assert config.enabled is True


# ═══════════════════════════════════════════════════════════════
# Test get_live2d_config (singleton)
# ═══════════════════════════════════════════════════════════════

class TestGetLive2DConfig:
    """Tests for get_live2d_config (singleton)"""

    def setup_method(self):
        """Reset global singleton before each test"""
        reset_live2d_config()

    @patch("animetta.config.live2d.Live2DConfig.from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_loads_from_yaml_when_config_exists(self, mock_exists, mock_from_yaml):
        """get_live2d_config loads from YAML file when config file exists"""
        expected_config = Live2DConfig(enabled=False)
        mock_from_yaml.return_value = expected_config

        config = get_live2d_config()

        mock_from_yaml.assert_called_once()
        assert config is expected_config

    @patch("pathlib.Path.exists", return_value=False)
    def test_returns_default_when_no_config_file(self, mock_exists):
        """get_live2d_config returns default Live2DConfig when YAML file missing"""
        config = get_live2d_config()
        assert isinstance(config, Live2DConfig)
        assert config.enabled is True

    @patch("animetta.config.live2d.Live2DConfig.from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_singleton_returns_same_instance(self, mock_exists, mock_from_yaml):
        """get_live2d_config returns the same cached instance on repeated calls"""
        mock_from_yaml.return_value = Live2DConfig()

        config1 = get_live2d_config()
        config2 = get_live2d_config()

        assert config1 is config2
        # from_yaml should be called only once
        assert mock_from_yaml.call_count == 1

    @patch("animetta.config.live2d.Live2DConfig.from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_reset_creates_new_instance(self, mock_exists, mock_from_yaml):
        """After reset_live2d_config, get_live2d_config creates new instance"""
        # Return a fresh Live2DConfig instance on each call
        mock_from_yaml.side_effect = [Live2DConfig(), Live2DConfig()]

        config1 = get_live2d_config()
        reset_live2d_config()
        config2 = get_live2d_config()

        assert config1 is not config2
        assert mock_from_yaml.call_count == 2

    @patch("pathlib.Path.exists", return_value=False)
    def test_returns_live2d_config_instance(self, mock_exists):
        """get_live2d_config always returns a Live2DConfig instance"""
        config = get_live2d_config()
        assert isinstance(config, Live2DConfig)
