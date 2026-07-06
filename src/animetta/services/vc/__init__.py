"""VC (Voice Conversion) service implementation module"""

from .factory import VCFactory
from .interface import VCInterface
from .mock_vc import MockVC

__all__ = [
    "VCInterface",
    "VCFactory",
    "MockVC",
    "RVCVC",
]


def __getattr__(name: str):
    if name == "RVCVC":
        from .rvc_vc import RVCVC

        return RVCVC
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
