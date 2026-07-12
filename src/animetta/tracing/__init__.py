"""
Anima Tracing — OpenTelemetry-based distributed tracing for service-level calls.

Legacy service proxy retained for providers not yet on observation adapters.
"""

from .proxy import TracingProxy

__all__ = ["TracingProxy"]
