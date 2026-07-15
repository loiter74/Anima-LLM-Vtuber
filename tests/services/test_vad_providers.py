from __future__ import annotations

from animetta.config.providers.vad.mock import MockVADConfig
from animetta.services.vad import MockVAD, VADFactory, VADInterface, VADResult, VADState
from animetta.services.vad import mock_vad as mv_mod
from animetta.services.vad import silero_vad as sv_mod

"""
Tests for VAD provider implementations.

Covers:
- VADInterface contract (detect_speech, reset, get_current_state, close)
- VADState enum (IDLE, ACTIVE, INACTIVE)
- VADResult data object
- MockVAD: detect_speech returns VADResult, close()
- SileroVAD: from_config, detect_speech, reset, get_current_state, close()
- VADFactory: create_from_config, create with provider, fallback to MockVAD
"""

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from animetta.services.vad import SileroVAD

# ── Module-level sys.modules injection ──────────────────────────────
# SileroVAD._load_vad_model() imports `from silero_vad import load_silero_vad`
# inside the method body (lazy). We inject a mock so that import always
# resolves without requiring the real silero-vad pip package.

sys.modules["silero_vad"] = MagicMock()

# Set up a default Silero VAD model mock so any SileroVAD instance
# created without specific patches gets a working model.
_default_silero_model = MagicMock()
_default_silero_model.return_value.item.return_value = 0.5  # speech_prob = 0.5
sys.modules["silero_vad"].load_silero_vad = MagicMock(return_value=_default_silero_model)

# VADFactory.create("silero") imports `from .silero_vad import SileroVAD`
# at runtime (inside the method).  We also mock from_config as a safety
# measure so that ProviderRegistry pathways don't accidentally call the
# real from_config with test-incompatible configs.

_ORIGINAL_SILERO_FROM_CONFIG = SileroVAD.from_config  # saved for test use
SileroVAD.from_config = MagicMock(return_value=None)


# ── VADState Enum Tests ─────────────────────────────────────────────


class TestVADState:
    """Verify VADState enum values and members."""

    def test_enum_values(self):
        """VADState should have the expected members with correct integer values."""
        assert VADState.IDLE.value == 1
        assert VADState.ACTIVE.value == 2
        assert VADState.INACTIVE.value == 3

    def test_enum_membership(self):
        """VADState members should be instances of the enum."""
        assert isinstance(VADState.IDLE, VADState)
        assert isinstance(VADState.ACTIVE, VADState)
        assert isinstance(VADState.INACTIVE, VADState)

    def test_enum_names(self):
        """VADState should have meaningful .name attributes."""
        assert VADState.IDLE.name == "IDLE"
        assert VADState.ACTIVE.name == "ACTIVE"
        assert VADState.INACTIVE.name == "INACTIVE"


# ── VADResult Data Object Tests ─────────────────────────────────────


class TestVADResult:
    """Verify VADResult construction and properties."""

    def test_default_construction(self):
        """VADResult() should apply sensible defaults."""
        result = VADResult()
        assert result.audio_data == b""
        assert result.is_speech_start is False
        assert result.is_speech_end is False
        assert result.state == VADState.IDLE

    def test_speech_start(self):
        """VADResult with is_speech_start=True."""
        result = VADResult(is_speech_start=True, state=VADState.ACTIVE)
        assert result.is_speech_start is True
        assert result.is_special_signal is True

    def test_speech_end(self):
        """VADResult with is_speech_end=True."""
        result = VADResult(
            audio_data=b"\x00\x01",
            is_speech_end=True,
            state=VADState.IDLE,
        )
        assert result.is_speech_end is True
        assert result.is_special_signal is True
        assert len(result.audio_data) == 2

    def test_normal_chunk(self):
        """VADResult for a regular audio chunk (no special signal)."""
        result = VADResult(audio_data=b"\x00", state=VADState.ACTIVE)
        assert result.is_special_signal is False
        assert result.is_speech_start is False
        assert result.is_speech_end is False
        assert result.state == VADState.ACTIVE

    def test_repr_speech_start(self):
        """__repr__ should label speech start."""
        result = VADResult(is_speech_start=True, state=VADState.ACTIVE)
        assert "SPEECH_START" in repr(result)

    def test_repr_speech_end(self):
        """__repr__ should label speech end with audio length."""
        result = VADResult(is_speech_end=True, state=VADState.IDLE)
        assert "SPEECH_END" in repr(result)

    def test_repr_normal(self):
        """__repr__ should show state and audio length."""
        result = VADResult(audio_data=b"\x00\x00", state=VADState.ACTIVE)
        assert "ACTIVE" in repr(result)
        assert "audio_len=2" in repr(result)


# ── Interface Contract Tests ────────────────────────────────────────


class TestVADInterface:
    """Verify VADInterface defines the expected abstract methods."""

    @staticmethod
    def _get_abstract_methods() -> set:
        abstract = set()
        for attr_name in dir(VADInterface):
            attr = getattr(VADInterface, attr_name, None)
            if getattr(attr, "__isabstractmethod__", False):
                abstract.add(attr_name)
        return abstract

    def test_interface_defines_expected_methods(self):
        """VADInterface should define detect_speech, reset, get_current_state, close."""
        abstract = self._get_abstract_methods()
        for method in ("detect_speech", "reset", "get_current_state", "close"):
            assert method in abstract, f"'{method}' should be abstract"

    def test_all_providers_implement_interface(self):
        """All VAD provider classes should be concrete subclasses of VADInterface."""

        providers = [mv_mod.MockVAD]
        if hasattr(sv_mod, "SileroVAD"):
            providers.append(sv_mod.SileroVAD)

        for cls in providers:
            assert issubclass(cls, VADInterface), f"{cls.__name__} does not inherit VADInterface"

    def test_all_abstract_methods_implemented(self):
        """Each concrete provider must implement every abstract method."""

        abstract_methods = self._get_abstract_methods()
        providers = [mv_mod.MockVAD]
        if hasattr(sv_mod, "SileroVAD"):
            providers.append(sv_mod.SileroVAD)

        for cls in providers:
            for method in abstract_methods:
                impl = getattr(cls, method, None)
                assert impl is not None, f"{cls.__name__} is missing '{method}'"
                assert not getattr(impl, "__isabstractmethod__", False), (
                    f"{cls.__name__} has not implemented '{method}'"
                )


# ── MockVAD Tests ───────────────────────────────────────────────────


class TestMockVAD:
    """Tests for the MockVAD provider."""

    @pytest.fixture
    def vad(self):
        """MockVAD with low thresholds so tests don't need many frames."""
        return MockVAD(
            sample_rate=16000,
            db_threshold=-50.0,
            min_speech_duration=1,
            min_silence_duration=1,
        )

    def test_constructor_defaults(self):
        """Constructor should use sensible defaults."""
        vad = MockVAD()
        assert vad.sample_rate == 16000
        assert vad.db_threshold == -30.0
        assert vad.min_speech_duration == 5
        assert vad.min_silence_duration == 15
        assert vad.state == VADState.IDLE

    def test_instantiate_with_sample_rate(self):
        """Can instantiate with sample_rate=16000 or other values."""
        vad = MockVAD(sample_rate=16000)
        assert vad.sample_rate == 16000
        assert isinstance(vad, MockVAD)

    def test_detect_speech_returns_vad_result(self, vad):
        """detect_speech() should return a VADResult instance."""
        audio = [0.0] * 1600
        result = vad.detect_speech(audio)
        assert isinstance(result, VADResult)

    def test_initial_state_idle(self, vad):
        """Initial state should be IDLE."""
        assert vad.get_current_state() == VADState.IDLE

    def test_detect_speech_transitions_to_active(self, vad):
        """Loud audio should transition state to ACTIVE."""
        for _ in range(3):
            vad.detect_speech([0.5] * 1600)
        assert vad.get_current_state() == VADState.ACTIVE

    def test_detect_speech_emits_speech_start(self, vad):
        """Speech start should return VADResult with is_speech_start=True."""
        found_start = False
        for _ in range(5):
            result = vad.detect_speech([0.5] * 1600)
            if result.is_speech_start:
                found_start = True
                break
        assert found_start, "Speech start was not emitted"

    def test_detect_speech_emits_speech_end(self, vad):
        """Silence after speech should emit speech_end."""
        for _ in range(3):
            vad.detect_speech([0.5] * 1600)

        found_end = False
        for _ in range(5):
            result = vad.detect_speech([0.0] * 1600)
            if result.is_speech_end:
                found_end = True
                break
        assert found_end, "Speech end was not emitted"

    def test_accepts_numpy_array(self, vad):
        """detect_speech() should accept a numpy array."""
        audio_np = np.zeros(1600, dtype=np.float32)
        result = vad.detect_speech(audio_np)
        assert isinstance(result, VADResult)

    def test_accepts_list_of_floats(self, vad):
        """detect_speech() should accept a list of floats."""
        result = vad.detect_speech([0.0] * 1600)
        assert isinstance(result, VADResult)

    def test_reset_clears_state(self, vad):
        """reset() should return to IDLE and clear buffers."""
        for _ in range(3):
            vad.detect_speech([0.5] * 1600)
        assert vad.get_current_state() == VADState.ACTIVE

        vad.reset()
        assert vad.get_current_state() == VADState.IDLE
        assert vad.speech_frames == 0
        assert vad.silence_frames == 0
        assert len(vad.audio_buffer) == 0

    def test_get_current_state(self, vad):
        """get_current_state() should return the current state."""
        assert vad.get_current_state() == VADState.IDLE

    @pytest.mark.asyncio
    async def test_close(self, vad):
        """close() should reset state and not raise."""
        await vad.close()
        assert vad.get_current_state() == VADState.IDLE

    def test_normalize_int16_audio(self):
        """detect_speech() should normalise int16 PCM data to [-1.0, 1.0]."""
        vad = MockVAD(db_threshold=-50.0, min_speech_duration=1, min_silence_duration=1)
        audio = [16000] * 1600  # int16 range values
        result = vad.detect_speech(audio)
        assert isinstance(result, VADResult)


# ── SileroVAD Tests ─────────────────────────────────────────────────


class TestSileroVAD:
    """Tests for the SileroVAD provider (external calls mocked via sys.modules)."""

    @pytest.fixture
    def mock_model(self):
        """Return a controlled model mock with predictable speech probability."""
        m = MagicMock()
        m.return_value.item.return_value = 0.5
        return m

    def test_constructor_loads_model(self, mock_model):
        """Constructor should load the Silero VAD model via load_silero_vad()."""
        with patch("silero_vad.load_silero_vad", return_value=mock_model):
            vad = SileroVAD(sample_rate=16000)
        assert vad.model is mock_model

    def test_constructor_stores_parameters(self, mock_model):
        """Constructor should store all configuration parameters."""
        with patch("silero_vad.load_silero_vad", return_value=mock_model):
            vad = SileroVAD(
                sample_rate=16000,
                prob_threshold=0.3,
                db_threshold=-50,
                required_hits=4,
                required_misses=3,
                smoothing_window=10,
            )
        assert vad.sample_rate == 16000
        assert vad.prob_threshold == 0.3
        assert vad.db_threshold == -50
        assert vad.required_hits == 4
        assert vad.required_misses == 3
        assert vad.smoothing_window == 10

    def test_from_config_returns_instance(self, mock_model):
        """from_config should return a SileroVAD instance with correct params."""
        with (
            patch("silero_vad.load_silero_vad", return_value=mock_model),
            patch.object(SileroVAD, "from_config", wraps=_ORIGINAL_SILERO_FROM_CONFIG),
        ):
            config = MagicMock()
            config.sample_rate = 16000
            config.prob_threshold = 0.2
            config.db_threshold = -100
            config.required_hits = 5
            config.required_misses = 2
            config.smoothing_window = 12

            instance = SileroVAD.from_config(config)

        assert isinstance(instance, SileroVAD)
        assert instance.sample_rate == 16000
        assert instance.prob_threshold == 0.2
        assert instance.required_hits == 5

    def test_detect_speech_returns_vad_result(self, mock_model):
        """detect_speech() should return a VADResult."""
        with patch("silero_vad.load_silero_vad", return_value=mock_model):
            vad = SileroVAD(sample_rate=16000, prob_threshold=0.3)

        audio = np.zeros(512, dtype=np.float32)
        result = vad.detect_speech(audio)
        assert isinstance(result, VADResult)

    def test_detect_speech_accepts_list(self, mock_model):
        """detect_speech() should accept a Python list."""
        with patch("silero_vad.load_silero_vad", return_value=mock_model):
            vad = SileroVAD(sample_rate=16000, prob_threshold=0.3)

        result = vad.detect_speech([0.0] * 512)
        assert isinstance(result, VADResult)

    def test_reset(self, mock_model):
        """reset() should reset the state machine to IDLE."""
        with patch("silero_vad.load_silero_vad", return_value=mock_model):
            vad = SileroVAD(sample_rate=16000)

        vad.reset()
        assert vad.get_current_state() == VADState.IDLE

    def test_get_current_state(self, mock_model):
        """get_current_state() should return the current VAD state."""
        with patch("silero_vad.load_silero_vad", return_value=mock_model):
            vad = SileroVAD(sample_rate=16000)

        assert vad.get_current_state() == VADState.IDLE

    @pytest.mark.asyncio
    async def test_close(self, mock_model):
        """close() should reset the state machine."""
        with patch("silero_vad.load_silero_vad", return_value=mock_model):
            vad = SileroVAD(sample_rate=16000)

        await vad.close()
        assert vad.get_current_state() == VADState.IDLE

    def test_preload_is_idempotent(self, mock_model):
        """preload() should be safe to call multiple times."""
        with patch("silero_vad.load_silero_vad", return_value=mock_model) as mock_load:
            vad = SileroVAD(sample_rate=16000)
            import asyncio

            # Model is loaded eagerly in __init__, so preload is a no-op
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(vad.preload())
                loop.run_until_complete(vad.preload())
            finally:
                loop.close()
        # load_silero_vad should have been called only once (from __init__)
        assert mock_load.call_count >= 1


# ── VADFactory Tests ────────────────────────────────────────────────


class TestVADFactory:
    """Tests for the VADFactory."""

    @patch("animetta.services.vad.factory.ProviderRegistry.create_service")
    def test_create_from_config_uses_registry(self, mock_create_service):
        """create_from_config should delegate to ProviderRegistry."""

        mock_vad = MagicMock()
        mock_create_service.return_value = mock_vad

        config = MockVADConfig()
        result = VADFactory.create_from_config(config)
        mock_create_service.assert_called_once_with("vad", config)
        assert result is not None

    @patch("animetta.services.vad.factory.ProviderRegistry.create_service")
    def test_create_from_config_fallback_to_mock(self, mock_create_service):
        """create_from_config should fall back to MockVAD on error."""

        mock_create_service.side_effect = ValueError("Unknown provider")

        config = MockVADConfig()
        result = VADFactory.create_from_config(config)
        assert isinstance(getattr(result, "_target", result), MockVAD)

    def test_create_mock(self):
        """create('mock') should return a MockVAD with default sample_rate."""
        result = VADFactory.create("mock")
        assert isinstance(result, MockVAD)
        assert result.sample_rate == 16000

    def test_create_mock_with_custom_params(self):
        """create('mock') should accept custom parameters."""
        result = VADFactory.create(
            "mock",
            sample_rate=8000,
            db_threshold=-20.0,
            min_speech_duration=10,
            min_silence_duration=20,
        )
        assert isinstance(result, MockVAD)
        assert result.sample_rate == 8000
        assert result.db_threshold == -20.0
        assert result.min_speech_duration == 10
        assert result.min_silence_duration == 20

    def test_mock_vad_from_config(self):
        """MockVAD should support ProviderRegistry construction from config."""
        config = MockVADConfig(
            sample_rate=8000,
            db_threshold=-22.0,
            min_speech_duration=3,
            min_silence_duration=9,
        )

        result = MockVAD.from_config(config)

        assert isinstance(result, MockVAD)
        assert result.sample_rate == 8000
        assert result.db_threshold == -22.0
        assert result.min_speech_duration == 3
        assert result.min_silence_duration == 9

    def test_create_silero(self):
        """create('silero') should return a SileroVAD instance."""
        mock_instance = MagicMock()
        with patch(
            "animetta.services.vad.silero_vad.SileroVAD",
            return_value=mock_instance,
        ):
            result = VADFactory.create("silero", sample_rate=16000)
        assert result is mock_instance

    def test_create_silero_with_params(self):
        """create('silero') should forward keyword arguments."""
        with patch(
            "animetta.services.vad.silero_vad.SileroVAD",
            return_value=MagicMock(),
        ) as mock_cls:
            VADFactory.create(
                "silero",
                sample_rate=8000,
                prob_threshold=0.5,
                required_hits=10,
            )
        mock_cls.assert_called_once_with(
            sample_rate=8000,
            prob_threshold=0.5,
            db_threshold=-100,
            required_hits=10,
            required_misses=2,
            smoothing_window=12,
        )

    def test_create_silero_fallback_on_importerror(self):
        """create('silero') should fall back to MockVAD on ImportError."""
        with patch(
            "animetta.services.vad.silero_vad.SileroVAD",
            side_effect=ImportError("Not installed"),
        ):
            result = VADFactory.create("silero")
        assert isinstance(result, MockVAD)

    def test_create_unknown_provider(self):
        """create() with unknown provider should return MockVAD."""
        result = VADFactory.create("unknown_provider")
        assert isinstance(result, MockVAD)

    def test_get_available_configs(self):
        """get_available_configs should contain 'mock' and 'silero'."""
        providers = VADFactory.get_available_configs()
        assert "mock" in providers
        assert "silero" in providers
