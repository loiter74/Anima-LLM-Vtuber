"""
Desktop client support
Manages Electron desktop client registration and broadcasting
"""

from loguru import logger

# Desktop client types
DESKTOP_CLIENT_TYPES = {"live2d", "chat", "web"}


class DesktopClientManager:
    """
    Desktop client manager

    Responsibilities:
    1. Manage desktop client registration
    2. Broadcast messages to clients of a specified type
    3. Client state tracking
    """

    def __init__(self):
        # Store desktop client info
        # Key: session_id, Value: {client_type: str, connected: bool}
        self.clients: dict[str, dict] = {}

    def register(self, sid: str, client_type: str = "web") -> bool:
        """
        Register a desktop client

        Args:
            sid: session id
            client_type: Client type ("live2d", "chat", "web")

        Returns:
            bool: Whether registration succeeded
        """
        if client_type not in DESKTOP_CLIENT_TYPES:
            logger.warning(f"[Desktop] Unknown client type: {client_type}")
            return False

        self.clients[sid] = {"client_type": client_type, "connected": True}

        logger.info(f"[Desktop] {client_type} client registered: {sid}")
        return True

    def unregister(self, sid: str) -> None:
        """
        Unregister a desktop client

        Args:
            sid: session id
        """
        if sid in self.clients:
            client_type = self.clients[sid].get("client_type", "unknown")
            del self.clients[sid]
            logger.info(f"[Desktop] {client_type} client unregistered: {sid}")

    def get_client_type(self, sid: str) -> str:
        """Get client type"""
        if sid in self.clients:
            return self.clients[sid].get("client_type", "web")
        return "web"

    def is_connected(self, sid: str) -> bool:
        """Check if client is connected"""
        if sid in self.clients:
            return self.clients[sid].get("connected", False)
        return False

    def set_connected(self, sid: str, connected: bool) -> None:
        """Set client connection state"""
        if sid in self.clients:
            self.clients[sid]["connected"] = connected

    def get_clients_by_type(self, client_type: str) -> set[str]:
        """
        Get all clients of a specified type

        Args:
            client_type: Client type

        Returns:
            Set[str]: Set of client session ids
        """
        return {
            sid
            for sid, info in self.clients.items()
            if info.get("client_type") == client_type and info.get("connected")
        }

    @property
    def client_count(self) -> int:
        """Get the number of registered clients"""
        return len(self.clients)
