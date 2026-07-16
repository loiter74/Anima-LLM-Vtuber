"""ASR service implementation module

Heavy providers (faster_whisper, funasr) are guarded with try/except
so that the module can be imported without their dependencies
in lightweight/core deployments.
"""

from importlib import import_module

from .factory import ASRFactory
from .interface import ASRInterface

# Core implementations (lightweight dependencies)
from .mock_asr import MockASR

_LAZY_PROVIDERS = {
    "GLMASR": (".glm_asr", "GLMASR"),
    "MimoASR": (".mimo_asr", "MimoASR"),
    "FasterWhisperASR": (".faster_whisper_asr", "FasterWhisperASR"),
    "FunASRASR": (".funasr_asr", "FunASRASR"),
}


def __getattr__(name: str):
    """Import optional provider implementations only when requested."""
    target = _LAZY_PROVIDERS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    try:
        value = getattr(import_module(module_name, __name__), attribute)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("animetta."):
            raise
        return None
    globals()[name] = value
    return value


__all__ = [
    "ASRInterface",
    "ASRFactory",
    # Core (always available)
    "MockASR",
    "GLMASR",
    "MimoASR",
    # Optional (may be None if deps missing)
    "FasterWhisperASR",
    "FunASRASR",
]
