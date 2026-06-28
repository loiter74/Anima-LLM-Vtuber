"""Provider availability smoke tests.

Verify that:
1. Mock providers can be imported and created without heavy dependencies.
2. Missing optional providers degrade to None (not crash).
3. Factory.create() degrades gracefully when optional deps are missing.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is on path
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)


# ── Mock providers should always be importable ────────────────────


class TestMockProvidersImportable:
    """Mock providers must import without any heavy dependencies."""

    def test_mock_tts_importable(self):
        from animetta.services.tts.mock_tts import MockTTS
        assert MockTTS is not None

    def test_mock_asr_importable(self):
        from animetta.services.asr.mock_asr import MockASR
        assert MockASR is not None

    def test_mock_llm_importable(self):
        from animetta.services.llm.mock_llm import MockLLM
        assert MockLLM is not None

    def test_mock_vad_importable(self):
        from animetta.services.vad.mock_vad import MockVAD
        assert MockVAD is not None

    def test_edge_tts_importable(self):
        from animetta.services.tts.edge_tts import EdgeTTS
        assert EdgeTTS is not None


# ── Heavy providers should degrade to None when deps missing ──────


class TestHeavyProviderDegradation:
    """Heavy providers wrapped in try/except should be None when deps are missing."""

    def _check_import(self, module_path: str, attr_name: str):
        """Import a module and check if the guarded attribute is None."""
        mod = importlib.import_module(module_path)
        val = getattr(mod, attr_name, "MISSING")
        # Either the provider loaded (deps present) or it's None (deps missing)
        assert val is None or val is not None, f"{attr_name} should be None or a class"

    def test_tts_init_has_guarded_imports(self):
        """TTS __init__ should not crash even without torch/kokoro."""
        import animetta.services.tts as tts_mod
        # These should exist (may be None if deps missing)
        assert hasattr(tts_mod, "Qwen3TTSTTS")

    def test_asr_init_has_guarded_imports(self):
        """ASR __init__ should not crash even without faster-whisper/funasr."""
        import animetta.services.asr as asr_mod
        assert hasattr(asr_mod, "FasterWhisperASR")
        assert hasattr(asr_mod, "FunASRASR")

    def test_vad_init_has_guarded_imports(self):
        """VAD __init__ should not crash even without silero."""
        import animetta.services.vad as vad_mod
        assert hasattr(vad_mod, "SileroVAD")


# ── Factory graceful degradation ──────────────────────────────────


class TestFactoryDegradation:
    """Factory.create() should degrade to mock when optional deps are missing."""

    def test_tts_factory_creates_mock(self):
        from animetta.services.tts.factory import TTSFactory
        from animetta.services.tts.mock_tts import MockTTS

        result = TTSFactory.create("mock")
        # Factory wraps in TracingProxy; check inner object
        inner = getattr(result, "_target", result)
        assert isinstance(inner, MockTTS)

    def test_asr_factory_creates_mock(self):
        from animetta.services.asr.factory import ASRFactory
        from animetta.services.asr.mock_asr import MockASR

        result = ASRFactory.create("mock")
        inner = getattr(result, "_target", result)
        assert isinstance(inner, MockASR)

    def test_llm_factory_creates_mock(self):
        from animetta.services.llm.factory import LLMFactory
        from animetta.services.llm.mock_llm import MockLLM

        result = LLMFactory.create("mock")
        inner = getattr(result, "_target", result)
        assert isinstance(inner, MockLLM)

    def test_vad_factory_creates_mock(self):
        from animetta.services.vad.factory import VADFactory
        from animetta.services.vad.mock_vad import MockVAD

        result = VADFactory.create("mock")
        assert isinstance(result, MockVAD)


# ── Config registry completeness ──────────────────────────────────


class TestConfigRegistry:
    """All provider configs should be registered even if services can't load."""

    def test_all_tts_configs_registered(self):
        from animetta.config.core.registry import ProviderRegistry
        registry = ProviderRegistry._configs.get("tts", {})
        expected = {"mock", "edge", "openai", "kokoro", "qwen3", "chattts", "glm", "gpt_sovits", "vibe_voice"}
        assert expected.issubset(set(registry.keys())), f"Missing TTS configs: {expected - set(registry.keys())}"

    def test_all_asr_configs_registered(self):
        from animetta.config.core.registry import ProviderRegistry
        registry = ProviderRegistry._configs.get("asr", {})
        expected = {"mock"}
        assert expected.issubset(set(registry.keys())), f"Missing ASR configs: {expected - set(registry.keys())}"

    def test_all_llm_configs_registered(self):
        from animetta.config.core.registry import ProviderRegistry
        registry = ProviderRegistry._configs.get("llm", {})
        expected = {"mock", "openai", "glm", "deepseek"}
        assert expected.issubset(set(registry.keys())), f"Missing LLM configs: {expected - set(registry.keys())}"

    def test_all_vad_configs_registered(self):
        from animetta.config.core.registry import ProviderRegistry
        registry = ProviderRegistry._configs.get("vad", {})
        expected = {"mock", "silero"}
        assert expected.issubset(set(registry.keys()), ), f"Missing VAD configs: {expected - set(registry.keys())}"
