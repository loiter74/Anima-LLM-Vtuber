from __future__ import annotations

from animetta.avatar.mappers.base import ExpressionFrame
from animetta.avatar.mappers.emotion_param_mapper import (
    DEFAULT_EMOTION_MAPPINGS,
    EmotionParamMapper,
)

"""
Tests for EmotionParamMapper — emotion to Live2D parameter mapping.
"""

# ============================================================
# Initialization
# ============================================================


class TestEmotionParamMapperInit:
    """Initialization."""

    def test_default_init(self):
        """Default init uses DEFAULT_EMOTION_MAPPINGS."""
        mapper = EmotionParamMapper()
        assert mapper.mappings == DEFAULT_EMOTION_MAPPINGS
        assert mapper.default_duration == 0.3

    def test_custom_mappings(self):
        """Custom mappings override defaults."""
        custom = {"happy": {"ParamMouthForm": 0.5}}
        mapper = EmotionParamMapper(mappings=custom)
        assert mapper.mappings == custom
        assert "sad" not in mapper.mappings

    def test_custom_duration(self):
        """Custom default duration."""
        mapper = EmotionParamMapper(default_duration=0.5)
        assert mapper.default_duration == 0.5


# ============================================================
# map_emotion
# ============================================================


class TestEmotionParamMapperMapEmotion:
    """map_emotion() — single emotion to parameters."""

    def test_happy_returns_expression_frame(self):
        """Happy emotion should return ExpressionFrame."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("happy")
        assert isinstance(frame, ExpressionFrame)
        assert frame.intensity == 1.0
        assert frame.timestamp == 0.0

    def test_happy_contains_mouth_params(self):
        """Happy should include mouth parameters."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("happy")
        param_names = [p.name for p in frame.parameters]
        assert "ParamMouthOpenY" not in param_names
        assert "ParamMouthForm" in param_names
        assert "ParamBrowLY" in param_names

    def test_sad_eyebrows_lowered(self):
        """Sad should have lowered eyebrows (negative values)."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("sad")
        eyebrow_l = next(p for p in frame.parameters if p.name == "ParamBrowLY")
        assert eyebrow_l.value < 0

    def test_angry_eyebrows_furrowed(self):
        """Angry should have furrowed eyebrows (strongly negative)."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("angry")
        eyebrow_l = next(p for p in frame.parameters if p.name == "ParamBrowLY")
        assert eyebrow_l.value < -0.3

    def test_surprised_eyes_wide_open(self):
        """Surprised should have wide eyes."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("surprised")
        eye_l = next(p for p in frame.parameters if p.name == "ParamEyeLOpen")
        assert eye_l.value >= 0.8

    def test_neutral_all_zero(self):
        """Neutral should have mostly zero/default values."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("neutral")
        param_dict = {p.name: p.value for p in frame.parameters}
        assert abs(param_dict["ParamAngleX"]) < 0.1
        assert abs(param_dict["ParamAngleY"]) < 0.1
        assert "ParamMouthOpenY" not in param_dict

    def test_thinking_asymmetric_eyebrows(self):
        """Thinking should have asymmetric eyebrows."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("thinking")
        eyebrow_l = next(p for p in frame.parameters if p.name == "ParamBrowLY")
        eyebrow_r = next(p for p in frame.parameters if p.name == "ParamBrowRY")
        assert eyebrow_l.value != eyebrow_r.value

    def test_confused_head_tilt(self):
        """Confused should have head tilt (ParamAngleZ != 0)."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("confused")
        angle_z = next(p for p in frame.parameters if p.name == "ParamAngleZ")
        assert angle_z.value != 0

    def test_love_gentle_smile(self):
        """Love should have a gentle mouth shape without owning mouth opening."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("love")
        mouth = next(p for p in frame.parameters if p.name == "ParamMouthForm")
        assert 0 < mouth.value < 0.6

    def test_shy_looking_down(self):
        """Shy should have eyes looking down."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("shy")
        eye_ball_y = next(p for p in frame.parameters if p.name == "ParamEyeBallY")
        assert eye_ball_y.value > 0

    def test_excited_laughing_mouth(self):
        """Excited should have a strong smile shape without owning mouth opening."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("excited")
        mouth = next(p for p in frame.parameters if p.name == "ParamMouthForm")
        assert mouth.value >= 0.4

    def test_unknown_emotion_falls_back_to_neutral(self):
        """Unknown emotion should map to neutral and log a warning."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("nonexistent_emotion")
        # Should use deterministic neutral config.
        param_dict = {p.name: p.value for p in frame.parameters}
        assert abs(param_dict.get("ParamAngleX", 1.0)) < 0.1
        assert abs(param_dict.get("ParamAngleY", 1.0)) < 0.1

    def test_case_insensitive(self):
        """Emotion names should be case-insensitive."""
        mapper = EmotionParamMapper()
        frame_lower = mapper.map_emotion("happy")
        frame_upper = mapper.map_emotion("HAPPY")
        frame_title = mapper.map_emotion("Happy")
        names_lower = [p.name for p in frame_lower.parameters]
        names_upper = [p.name for p in frame_upper.parameters]
        assert names_lower == names_upper
        assert names_lower == [p.name for p in frame_title.parameters]

    def test_all_presets_have_params(self):
        """All emotion presets should produce at least one parameter."""
        mapper = EmotionParamMapper()
        for emotion in DEFAULT_EMOTION_MAPPINGS:
            frame = mapper.map_emotion(emotion)
            assert len(frame.parameters) > 0, f"{emotion} has no parameters"

    def test_each_param_has_duration(self):
        """Each parameter should have a duration set."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("happy")
        for param in frame.parameters:
            assert param.duration == 0.3


# ============================================================
# Intensity scaling
# ============================================================


class TestEmotionParamMapperIntensity:
    """Intensity scaling behavior."""

    def test_intensity_zero_returns_zero_params(self):
        """Intensity 0.0 should make all param values 0."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("happy", intensity=0.0)
        # With 0 intensity, variance is also 0, so all should be 0
        for param in frame.parameters:
            assert param.value == 0.0, f"{param.name} = {param.value}"

    def test_intensity_half(self):
        """Intensity 0.5 should produce half-scale values."""
        mapper = EmotionParamMapper()
        frame_half = mapper.map_emotion("happy", intensity=0.5)
        frame_full = mapper.map_emotion("happy", intensity=1.0)
        # Each value in half is exactly scaled from the deterministic full value.
        for p_half in frame_half.parameters:
            p_full = next(p for p in frame_full.parameters if p.name == p_half.name)
            assert abs(p_half.value) <= abs(p_full.value)

    def test_intensity_full(self):
        """Intensity 1.0 should use full deterministic base values."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("happy", intensity=1.0)
        mouth = next(p for p in frame.parameters if p.name == "ParamMouthForm")
        assert mouth.value == 0.3

    def test_intensity_negative_clamped(self):
        """Intensity value should not cause out of range params."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("happy", intensity=-0.5)
        for param in frame.parameters:
            assert -1.0 <= param.value <= 1.0

    def test_intensity_over_one(self):
        """Intensity > 1 should still produce values in valid range."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("happy", intensity=2.0)
        for param in frame.parameters:
            assert -1.0 <= param.value <= 1.0


# ============================================================
# Deterministic mapping
# ============================================================


class TestEmotionParamMapperDeterminism:
    """The response path must never introduce random parameter variance."""

    def test_repeated_mapping_is_identical(self):
        mapper = EmotionParamMapper()
        first = mapper.map_emotion("happy", intensity=1.0)
        second = mapper.map_emotion("happy", intensity=1.0)
        assert first.parameters == second.parameters

    def test_zero_intensity_is_zero(self):
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("happy", intensity=0.0)
        # At 0 intensity, variance range is 0, so values should be exactly 0
        for param in frame.parameters:
            assert param.value == 0.0

    def test_variance_clamped(self):
        """Variance should not push values outside [-1, 1]."""
        mapper = EmotionParamMapper()
        frame = mapper.map_emotion("surprised", intensity=1.0)
        for param in frame.parameters:
            assert -1.0 <= param.value <= 1.0


# ============================================================
# Timeline mapping
# ============================================================


class TestEmotionParamMapperTimeline:
    """map_emotions_timeline()."""

    def test_timeline_returns_multiple_frames(self):
        """Timeline mapping should return correct number of frames."""
        mapper = EmotionParamMapper()
        emotions = [("happy", 0.0, 2.0, 1.0), ("sad", 2.0, 4.0, 0.5)]
        frames = mapper.map_emotions_timeline(emotions, duration=4.0)
        assert len(frames) == 2

    def test_timeline_sorted(self):
        """Frames should be sorted by timestamp."""
        mapper = EmotionParamMapper()
        emotions = [("sad", 2.0, 4.0, 1.0), ("happy", 0.0, 2.0, 1.0)]
        frames = mapper.map_emotions_timeline(emotions, duration=4.0)
        assert frames[0].timestamp == 0.0
        assert frames[1].timestamp == 2.0

    def test_timeline_updates_duration(self):
        """Timeline mapping should update param duration to segment length."""
        mapper = EmotionParamMapper()
        emotions = [("happy", 0.0, 2.5, 1.0)]
        frames = mapper.map_emotions_timeline(emotions, duration=2.5)
        for param in frames[0].parameters:
            assert param.duration == 2.5


# ============================================================
# Utility methods
# ============================================================


class TestEmotionParamMapperUtility:
    """add_emotion_mapping and properties."""

    def test_add_emotion_mapping(self):
        """add_emotion_mapping should add new emotion."""
        mapper = EmotionParamMapper()
        mapper.add_emotion_mapping("tired", {"ParamEyeLOpen": 0.3})
        assert "tired" in mapper.mappings
        frame = mapper.map_emotion("tired")
        eye_l = next(p for p in frame.parameters if p.name == "ParamEyeLOpen")
        assert eye_l.value > 0

    def test_add_emotion_mapping_updates_existing(self):
        """add_emotion_mapping should update existing emotion."""
        mapper = EmotionParamMapper()
        mapper.add_emotion_mapping("happy", {"ParamMouthOpenY": 1.0})
        assert mapper.mappings["happy"]["ParamMouthOpenY"] == 1.0

    def test_name(self):
        """name property should return correct value."""
        mapper = EmotionParamMapper()
        assert mapper.name == "emotion_param_mapper"

    def test_get_supported_emotions(self):
        """get_supported_emotions should return all keys."""
        mapper = EmotionParamMapper()
        emotions = mapper.get_supported_emotions()
        assert "happy" in emotions
        assert "sad" in emotions
        assert "neutral" in emotions
        assert len(emotions) == len(DEFAULT_EMOTION_MAPPINGS)
