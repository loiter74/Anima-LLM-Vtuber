"""Read-only mirrors fed exclusively from committed observation records."""

from .otel import OTelMirror
from .prometheus import PrometheusMirror

__all__ = ["OTelMirror", "PrometheusMirror"]
