"""Public service APIs without cross-domain import side effects.

Subpackages are loaded only when their exported symbol is requested.  This keeps
standalone workers, such as the Qwen TTS image, independent from unrelated LLM,
ASR, singing, and audio dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .asr import ASRFactory as ASRFactory
    from .asr import ASRInterface as ASRInterface
    from .audio import AudioProcessorInterface as AudioProcessorInterface
    from .audio.vad_audio_processor import VADAudioProcessor as VADAudioProcessor
    from .llm import LLMFactory as LLMFactory
    from .llm import LLMInterface as LLMInterface
    from .singing import SingingService as SingingService
    from .singing import SVCPipeline as SVCPipeline
    from .tts import TTSFactory as TTSFactory
    from .tts import TTSInterface as TTSInterface
    from .vad import VADFactory as VADFactory
    from .vad import VADInterface as VADInterface

_EXPORTS = {
    "LLMInterface": (".llm", "LLMInterface"),
    "LLMFactory": (".llm", "LLMFactory"),
    "ASRInterface": (".asr", "ASRInterface"),
    "ASRFactory": (".asr", "ASRFactory"),
    "TTSInterface": (".tts", "TTSInterface"),
    "TTSFactory": (".tts", "TTSFactory"),
    "VADInterface": (".vad", "VADInterface"),
    "VADFactory": (".vad", "VADFactory"),
    "AudioProcessorInterface": (".audio", "AudioProcessorInterface"),
    "VADAudioProcessor": (".audio.vad_audio_processor", "VADAudioProcessor"),
    "SingingService": (".singing", "SingingService"),
    "SVCPipeline": (".singing", "SVCPipeline"),
}


def __getattr__(name: str) -> Any:
    """Load one public service domain on first access."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy public names to introspection tools."""
    return sorted({*globals(), *_EXPORTS})


__all__ = list(_EXPORTS)
