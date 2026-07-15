"""
Service availability detection for optional runtime dependencies.

Provides centralized feature detection so optional services can decide
whether to initialize or skip gracefully, without logging ERROR-level noise.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from loguru import logger

# Cache results so we only check once per process lifetime
_AVAILABILITY_CACHE: dict[str, bool] = {}


def _detect_once(key: str) -> bool:
    """Run detection once and cache the result."""
    if key not in _AVAILABILITY_CACHE:
        _AVAILABILITY_CACHE[key] = _DETECTORS[key]()
    return _AVAILABILITY_CACHE[key]


def _has_node() -> bool:
    """Check if Node.js is available on PATH."""
    return shutil.which("node") is not None


def _has_mcp_package() -> bool:
    """Check if the Python MCP package is installed."""
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:
        return False


def _has_mcp_filesystem_server() -> bool:
    """Check if the MCP filesystem server binary exists."""
    paths = [
        "/usr/local/bin/mcp-server-filesystem",
        shutil.which("mcp-server-filesystem") or "",
    ]
    return any(p and Path(p).exists() for p in paths)


_DETECTORS = {
    "node": _has_node,
    "mcp_package": _has_mcp_package,
    "mcp_filesystem_server": _has_mcp_filesystem_server,
}


def is_service_available(service: str) -> bool:
    """
    Check if an optional service runtime is available.

    Args:
        service: One of 'node', 'mcp_package', 'mcp_filesystem_server'

    Returns:
        True if the runtime dependency is detected, False otherwise.
    """
    if service not in _DETECTORS:
        logger.warning(f"[availability] Unknown service: {service}")
        return False
    return _detect_once(service)


def get_availability_summary() -> str:
    """Return a one-line summary of optional service availability."""
    parts = []
    for name, detector in _DETECTORS.items():
        status = "available" if _detect_once(name) else "skipped"
        parts.append(f"{name}={status}")
    return "[startup] Optional services: " + ", ".join(parts)
