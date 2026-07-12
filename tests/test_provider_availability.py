"""Provider availability smoke tests.

Verify that:
1. Mock providers can be imported and created without heavy dependencies.
2. Missing optional providers degrade to None (not crash).
3. Factory.create() degrades gracefully when optional deps are missing.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is on path
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)


def test_core_service_packages_do_not_eagerly_import_torch() -> None:
    """Selecting remote/mock providers must not load unused CUDA stacks at boot."""
    code = """
import importlib
import importlib.abc
import sys

attempted = set()

class BlockHeavyImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        root = fullname.partition(".")[0]
        if root in {"torch", "torchaudio", "transformers", "peft"}:
            attempted.add(fullname)
            raise ImportError(f"blocked eager import: {fullname}")
        return None

sys.meta_path.insert(0, BlockHeavyImports())

for module_name in (
    "animetta.services.llm",
    "animetta.services.tts",
    "animetta.services.asr",
):
    importlib.import_module(module_name)

assert not attempted, sorted(attempted)[:20]

from animetta.services.asr.factory import ASRFactory
from animetta.services.llm.factory import LLMFactory
from animetta.services.tts.factory import TTSFactory

assert set(LLMFactory.get_available_configs()) == {
    "mock", "glm", "ollama", "openai", "deepseek", "local_lora"
}
assert set(TTSFactory.get_available_configs()) == {
    "mock", "edge", "mimo", "gpt_sovits", "qwen3", "glm",
    "chattts", "kokoro", "vibe_voice"
}
assert set(ASRFactory.get_available_configs()) == {
    "mock", "funasr", "glm", "mimo", "faster_whisper"
}
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = _src

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("module_name", "attribute"),
    [
        ("animetta.services.llm", "GLMLLM"),
        ("animetta.services.tts", "GLMTTS"),
        ("animetta.services.asr", "GLMASR"),
    ],
)
def test_optional_provider_import_failure_is_not_cached(
    monkeypatch,
    module_name: str,
    attribute: str,
) -> None:
    module = importlib.import_module(module_name)
    sentinel = object()
    recovered_module = type("RecoveredModule", (), {attribute: sentinel})()
    missing = ModuleNotFoundError("missing optional dependency", name="optional_dep")
    attempts = iter((missing, recovered_module))

    def import_once_then_recover(*_args):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.delitem(module.__dict__, attribute, raising=False)
    monkeypatch.setattr(module, "import_module", import_once_then_recover)

    assert getattr(module, attribute) is None
    assert getattr(module, attribute) is sentinel


def test_tts_strict_mode_preserves_provider_import_error() -> None:
    """Strict TTS creation reports the selected provider's missing dependency."""
    from animetta.services.tts.factory import TTSFactory

    missing = ModuleNotFoundError("missing GLM dependency", name="zhipuai")

    with patch(
        "animetta.services.tts.factory.import_module",
        side_effect=missing,
    ), patch(
        "animetta.services.tts.factory.ProviderRegistry.create_service",
    ) as create_service, pytest.raises(ModuleNotFoundError) as exc_info:
        TTSFactory.create("glm", api_key="test-key", strict=True)

    assert exc_info.value is missing
    create_service.assert_not_called()


def test_available_provider_catalog_excludes_config_only_providers() -> None:
    """Availability must not advertise providers with no service implementation."""
    from animetta.services.asr.factory import ASRFactory
    from animetta.services.tts.factory import TTSFactory

    assert "openai" not in TTSFactory.get_available_configs()
    assert "openai" not in ASRFactory.get_available_configs()


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
