from __future__ import annotations

"""
Tests for mapper base — ParameterState, ExpressionFrame, IEmotionParamMapper.
"""

from abc import ABC

import pytest

from animetta.avatar.mappers.base import ExpressionFrame, IEmotionParamMapper, ParameterState

# ============================================================
# ParameterState
# ============================================================


class TestParameterState:
    """ParameterState dataclass."""

    def test_create_with_defaults(self):
        """Create with name and value only."""
        param = ParameterState(name="ParamMouthOpenY", value=0.5)
        assert param.name == "ParamMouthOpenY"
        assert param.value == 0.5
        assert param.duration == 0.3  # default

    def test_create_with_all_fields(self):
        """Create with all fields."""
        param = ParameterState(name="ParamEyeLOpen", value=1.0, duration=0.5)
        assert param.name == "ParamEyeLOpen"
        assert param.value == 1.0
        assert param.duration == 0.5

    def test_to_dict(self):
        """to_dict should return correct dict."""
        param = ParameterState(name="Test", value=0.8, duration=0.3)
        d = param.to_dict()
        assert d == {"name": "Test", "value": 0.8, "duration": 0.3}

    def test_negative_value(self):
        """Parameter value can be negative."""
        param = ParameterState(name="ParamAngleZ", value=-0.5)
        assert param.value == -0.5

    def test_value_types(self):
        """Value should accept float."""
        param = ParameterState(name="Test", value=0.0)
        assert isinstance(param.value, float)

    def test_duration_must_be_positive(self):
        """Duration can be 0 or positive."""
        param = ParameterState(name="Test", value=0.5, duration=0.0)
        assert param.duration == 0.0
        param2 = ParameterState(name="Test2", value=0.5, duration=1.0)
        assert param2.duration == 1.0


# ============================================================
# ExpressionFrame
# ============================================================


class TestExpressionFrame:
    """ExpressionFrame dataclass."""

    def test_create_with_defaults(self):
        """Create with parameters list only."""
        params = [ParameterState("P1", 0.5)]
        frame = ExpressionFrame(parameters=params)
        assert frame.parameters == params
        assert frame.intensity == 1.0  # default
        assert frame.timestamp == 0.0  # default

    def test_create_with_all_fields(self):
        """Create with all fields."""
        params = [ParameterState("P1", 0.5)]
        frame = ExpressionFrame(parameters=params, intensity=0.8, timestamp=1.5)
        assert frame.intensity == 0.8
        assert frame.timestamp == 1.5

    def test_to_dict(self):
        """to_dict should return correct dict."""
        params = [ParameterState("P1", 0.5), ParameterState("P2", -0.3)]
        frame = ExpressionFrame(parameters=params, intensity=0.7, timestamp=2.0)
        d = frame.to_dict()
        assert d["intensity"] == 0.7
        assert d["timestamp"] == 2.0
        assert len(d["parameters"]) == 2
        assert d["parameters"][0]["name"] == "P1"
        assert d["parameters"][0]["value"] == 0.5

    def test_empty_parameters(self):
        """ExpressionFrame can have empty parameters list."""
        frame = ExpressionFrame(parameters=[])
        assert frame.parameters == []
        assert frame.to_dict()["parameters"] == []

    def test_multiple_parameters(self):
        """Frame with multiple parameters."""
        params = [
            ParameterState("Mouth", 0.6),
            ParameterState("EyeL", 0.9),
            ParameterState("EyeR", 0.9),
        ]
        frame = ExpressionFrame(parameters=params)
        assert len(frame.parameters) == 3


# ============================================================
# IEmotionParamMapper interface
# ============================================================


class TestIEmotionParamMapperInterface:
    """IEmotionParamMapper ABC."""

    def test_is_abstract(self):
        """IEmotionParamMapper should be an ABC."""
        assert issubclass(IEmotionParamMapper, ABC)

    def test_cannot_instantiate(self):
        """Cannot instantiate abstract interface directly."""
        with pytest.raises(TypeError):
            IEmotionParamMapper()  # type: ignore

    def test_map_emotion_is_abstract(self):
        """map_emotion should be abstract."""
        assert hasattr(IEmotionParamMapper.map_emotion, "__isabstractmethod__")

    def test_map_emotions_timeline_is_abstract(self):
        """map_emotions_timeline should be abstract."""
        assert hasattr(IEmotionParamMapper.map_emotions_timeline, "__isabstractmethod__")

    def test_name_property_is_abstract(self):
        """name should be abstract property."""
        assert hasattr(IEmotionParamMapper.name, "__isabstractmethod__")


class TestIEmotionParamMapperConcreteMethods:
    """IEmotionParamMapper concrete (non-abstract) methods."""

    def test_get_supported_emotions_default(self):
        """get_supported_emotions should return empty list by default."""
        mapper = _create_concrete_mapper()
        assert mapper.get_supported_emotions() == []

    def test_apply_intensity_half(self):
        """apply_intensity with 0.5 should halve the value."""
        mapper = _create_concrete_mapper()
        result = mapper.apply_intensity(0.6, 0.5)
        assert result == 0.3

    def test_apply_intensity_zero(self):
        """apply_intensity with 0 should return 0."""
        mapper = _create_concrete_mapper()
        result = mapper.apply_intensity(0.6, 0.0)
        assert result == 0.0

    def test_apply_intensity_full(self):
        """apply_intensity with 1.0 should return original value."""
        mapper = _create_concrete_mapper()
        result = mapper.apply_intensity(0.6, 1.0)
        assert result == 0.6

    def test_apply_intensity_negative(self):
        """apply_intensity with negative value should work."""
        mapper = _create_concrete_mapper()
        result = mapper.apply_intensity(-0.3, 0.5)
        assert result == -0.15


# Helper: create a concrete IEmotionParamMapper for testing default methods.
def _create_concrete_mapper():
    """Create a minimal concrete mapper for testing interface defaults."""

    class ConcreteMapper(IEmotionParamMapper):
        def map_emotion(self, emotion, intensity=1.0, context=None):
            return ExpressionFrame(parameters=[])

        def map_emotions_timeline(self, emotions, duration):
            return []

        @property
        def name(self):
            return "concrete_test"

    return ConcreteMapper()
