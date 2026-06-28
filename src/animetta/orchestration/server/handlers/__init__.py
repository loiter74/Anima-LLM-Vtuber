"""
Route handler modules — extracted from admin_handlers.py by domain.

Each module contains a handler class that receives the same
infrastructure dependencies (sio, session_manager, desktop_manager,
live2d_manager). BaseSocketHandler provides shared utilities
(_get_or_create_orchestrator, broadcast_to_desktop_clients, etc.).
"""

from .base_handler import BaseSocketHandler
from .bilibili_handlers import BilibiliHandlers
from .chat_handlers import ChatHandlers
from .config_handlers import ConfigHandlers
from .lifecycle_handlers import LifecycleHandlers
from .live2d_handlers import Live2DHandlers
from .persona_handlers import PersonaHandlers

__all__ = [
    "BaseSocketHandler",
    "BilibiliHandlers",
    "ChatHandlers",
    "ConfigHandlers",
    "LifecycleHandlers",
    "Live2DHandlers",
    "PersonaHandlers",
]
