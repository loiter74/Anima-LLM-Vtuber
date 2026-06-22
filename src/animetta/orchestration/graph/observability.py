"""
Observability integration - LangSmith + LangFuse

Responsibilities:
1. Load config/observability.yaml configuration
2. Initialize LangSmith (via environment variables, LangGraph native integration)
3. Initialize LangFuse CallbackHandler
4. Provide merged callbacks list to inject into LangGraph config
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from loguru import logger


class ObservabilityManager:
    """Observability manager - singleton"""

    _instance: Optional["ObservabilityManager"] = None

    def __new__(cls) -> "ObservabilityManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._langfuse_handler: Any | None = None
        self._langfuse_client: Any | None = None
        self._langsmith_enabled: bool = False
        self._langfuse_enabled: bool = False
        self._config: dict[str, Any] = {}

    def initialize(self, config_path: str | None = None) -> None:
        """
        Initialize observability

        Args:
            config_path: Config file path, default config/observability.yaml
        """
        if self._initialized:
            return

        # Load configuration
        self._config = self._load_config(config_path)

        # Initialize LangSmith (environment variable)
        self._init_langsmith()

        # Initialize LangFuse (CallbackHandler)
        self._init_langfuse()

        self._initialized = True
        self._log_status()

    def _load_config(self, config_path: str | None = None) -> dict[str, Any]:
        """Load configuration file"""
        if config_path is None:
            config_path = (
                Path(__file__).parent.parent.parent.parent.parent
                / "config" / "observability.yaml"
            )

        config_path = Path(config_path)
        if not config_path.exists():
            logger.info("[Observability] Config file not found, using defaults (all disabled)")
            return {"langsmith": {"enabled": False}, "langfuse": {"enabled": False}}

        try:
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            logger.info(f"[Observability] Config loaded: {config_path}")
            return config
        except Exception as e:
            logger.warning(f"[Observability] Config load failed: {e}")
            return {"langsmith": {"enabled": False}, "langfuse": {"enabled": False}}

    def _init_langsmith(self) -> None:
        """Initialize LangSmith - via environment variables, LangGraph auto-collection"""
        cfg = self._config.get("langsmith", {})
        if not cfg.get("enabled", False):
            return

        os.environ["LANGCHAIN_TRACING_V2"] = "true"

        if cfg.get("api_key"):
            os.environ["LANGCHAIN_API_KEY"] = cfg["api_key"]
        if cfg.get("project"):
            os.environ["LANGCHAIN_PROJECT"] = cfg["project"]
        if cfg.get("endpoint"):
            os.environ["LANGCHAIN_ENDPOINT"] = cfg["endpoint"]

        self._langsmith_enabled = True
        logger.info("[Observability] LangSmith enabled")

    def _init_langfuse(self) -> None:
        """Initialize LangFuse - via CallbackHandler

        Langfuse v4: CallbackHandler only accepts public_key,
        secret_key/host are automatically read from environment variables:
          LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
        """
        cfg = self._config.get("langfuse", {})
        if not cfg.get("enabled", False):
            return

        try:
            from langfuse.langchain import CallbackHandler
        except ImportError:
            logger.warning("[Observability] langfuse not installed or version too low, run: pip install langfuse>=4.0.0")
            return

        # Set environment variables (if YAML config has values, write them for Langfuse SDK to read)
        if cfg.get("secret_key") and not os.environ.get("LANGFUSE_SECRET_KEY"):
            os.environ["LANGFUSE_SECRET_KEY"] = cfg["secret_key"]
        if cfg.get("host") and not os.environ.get("LANGFUSE_HOST"):
            os.environ["LANGFUSE_HOST"] = cfg["host"]

        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", cfg.get("public_key"))
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", cfg.get("secret_key"))

        if not public_key or not secret_key:
            logger.warning("[Observability] LangFuse missing public_key/secret_key, skipped")
            return

        host = os.environ.get("LANGFUSE_HOST", cfg.get("host", "https://cloud.langfuse.com"))

        try:
            # Langfuse v4: Must create Langfuse client first, then create CallbackHandler (without passing public_key)
            from langfuse import Langfuse
            self._langfuse_client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
            self._langfuse_handler = CallbackHandler()
            self._langfuse_enabled = True
            logger.info(f"[Observability] LangFuse enabled - host: {host}")
        except Exception as e:
            logger.error(f"[Observability] LangFuse initialization failed: {e}")

    def _log_status(self) -> None:
        """Log current status"""
        parts = []
        if self._langsmith_enabled:
            parts.append("LangSmith=ON")
        if self._langfuse_enabled:
            parts.append("LangFuse=ON")
        if not parts:
            parts.append("All disabled")
        logger.info(f"[Observability] Status: {', '.join(parts)}")

    @property
    def callbacks(self) -> list[Any]:
        """Return LangGraph/LangChain callback list"""
        if self._langfuse_handler:
            return [self._langfuse_handler]
        return []

    @property
    def langsmith_enabled(self) -> bool:
        return self._langsmith_enabled

    @property
    def langfuse_enabled(self) -> bool:
        return self._langfuse_enabled

    def get_status(self) -> dict[str, Any]:
        """Get current status"""
        return {
            "langsmith_enabled": self._langsmith_enabled,
            "langfuse_enabled": self._langfuse_enabled,
        }


def get_observability() -> ObservabilityManager:
    """Get the global observability manager"""
    return ObservabilityManager()
