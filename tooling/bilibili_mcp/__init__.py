"""Development-only MCP control plane for Animetta's Bilibili session."""

from .controller import BilibiliController
from .server import create_server

__all__ = ["BilibiliController", "create_server"]
