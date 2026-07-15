"""
Server module

Contains WebSocket server, session management, route handling and lifecycle management
"""

from .desktop import DESKTOP_CLIENT_TYPES, DesktopClientManager
from .lifecycle import LifecycleManager
from .live2d import Live2DManager
from .routes import RouteHandlers, register_routes
from .session import SessionManager
from .websocket import WebSocketServer, create_server

__all__ = [
    # Server
    "WebSocketServer",
    "create_server",
    # Session management
    "SessionManager",
    # Routes
    "RouteHandlers",
    "register_routes",
    # Lifecycle
    "LifecycleManager",
    # Desktop client
    "DesktopClientManager",
    "DESKTOP_CLIENT_TYPES",
    # Live2D
    "Live2DManager",
]
