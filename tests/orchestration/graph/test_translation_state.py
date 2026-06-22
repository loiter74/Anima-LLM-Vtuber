from __future__ import annotations

"""Tests for translation runtime configuration state."""

import pytest

from animetta.orchestration.graph.translation_state import TranslationState, translation_state


class TestTranslationStateInit:
    """TranslationState default initialization."""

    def test_default_enabled(self):
        """Translation is enabled by default."""
        ts = TranslationState()
        assert ts.enabled is True

    def test_default_languages(self):
        """Default target=English, source=Chinese."""
        ts = TranslationState()
        assert ts.target_language == "English"
        assert ts.source_language == "Chinese"

    def test_independent_instances(self):
        """Each TranslationState instance is independent."""
        ts1 = TranslationState()
        ts2 = TranslationState()
        ts1.enabled = False
        assert ts2.enabled is True


class TestTranslationStateToggle:
    """Enable/disable toggling."""

    def test_disable_translation(self):
        """Setting enabled=False disables translation."""
        ts = TranslationState()
        ts.enabled = False
        assert ts.enabled is False

    def test_reenable_translation(self):
        """Toggling back to True re-enables translation."""
        ts = TranslationState()
        ts.enabled = False
        ts.enabled = True
        assert ts.enabled is True

    def test_toggle_multiple_times(self):
        """Even number of toggles returns to original state."""
        ts = TranslationState()
        for _ in range(10):
            ts.enabled = not ts.enabled
        # 10 is even → back to original (True)
        assert ts.enabled is True

    def test_toggle_odd_times(self):
        """Odd number of toggles flips the state."""
        ts = TranslationState()
        for _ in range(3):
            ts.enabled = not ts.enabled
        # 3 is odd → flipped from original (True → False)
        assert ts.enabled is False

    def test_set_enabled_to_bool_values(self):
        """enabled accepts bool-like values."""
        ts = TranslationState()
        ts.enabled = True
        assert ts.enabled is True
        ts.enabled = False
        assert ts.enabled is False


class TestTranslationStateLanguage:
    """Language configuration get/set."""

    def test_default_target_language(self):
        """Default target language is English."""
        ts = TranslationState()
        assert ts.target_language == "English"

    def test_default_source_language(self):
        """Default source language is Chinese."""
        ts = TranslationState()
        assert ts.source_language == "Chinese"

    def test_set_target_language(self):
        """target_language can be changed."""
        ts = TranslationState()
        ts.target_language = "Japanese"
        assert ts.target_language == "Japanese"

    def test_source_language_is_read_only(self):
        """source_language has no setter (read-only property)."""
        ts = TranslationState()
        assert ts.source_language == "Chinese"
        with pytest.raises(AttributeError, match="has no setter"):
            ts.source_language = "English"

    def test_set_target_language_to_empty_string(self):
        """target_language accepts empty string."""
        ts = TranslationState()
        ts.target_language = ""
        assert ts.target_language == ""

    def test_target_change_does_not_affect_source(self):
        """Setting target_language leaves source_language unchanged."""
        ts = TranslationState()
        ts.target_language = "French"
        assert ts.target_language == "French"
        assert ts.source_language == "Chinese"  # unchanged


class TestTranslationStateToDict:
    """to_dict() serialization."""

    def test_to_dict_defaults(self):
        """to_dict returns the default configuration."""
        ts = TranslationState()
        d = ts.to_dict()
        assert d == {
            "enabled": True,
            "target_language": "English",
            "source_language": "Chinese",
        }

    def test_to_dict_after_toggle(self):
        """to_dict reflects disabled state."""
        ts = TranslationState()
        ts.enabled = False
        assert ts.to_dict()["enabled"] is False

    def test_to_dict_after_language_change(self):
        """to_dict reflects updated target_language."""
        ts = TranslationState()
        ts.target_language = "Korean"
        d = ts.to_dict()
        assert d["target_language"] == "Korean"
        assert d["source_language"] == "Chinese"  # unchanged

    def test_to_dict_returns_new_dict(self):
        """to_dict returns a new dict each time (no shared reference)."""
        ts = TranslationState()
        d1 = ts.to_dict()
        d2 = ts.to_dict()
        d1["enabled"] = False
        assert d2["enabled"] is True


class TestTranslationStateSingleton:
    """Module-level singleton exists."""

    def test_singleton_importable(self):
        """The module-level translation_state singleton is accessible."""

        assert isinstance(translation_state, TranslationState)

    def test_singleton_is_same_object(self):
        """Repeated imports return the same singleton."""

        from animetta.orchestration.graph.translation_state import translation_state as ts1
        from animetta.orchestration.graph.translation_state import translation_state as ts2

        assert ts1 is ts2
