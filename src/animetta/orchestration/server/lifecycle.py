"""
Server lifecycle management
Graceful shutdown and resource cleanup
"""

import asyncio
import contextlib
import signal
import sys
from collections.abc import Callable

from loguru import logger


class LifecycleManager:
    """
    Lifecycle manager

    Responsibilities:
    1. Signal handler registration
    2. Graceful shutdown
    3. Resource cleanup
    """

    def __init__(self):
        self._shutdown_event: asyncio.Event | None = None
        self._cleanup_callbacks: list = []
        self._signal_handlers_set = False
        self._shutting_down = False

    def setup_signal_handlers(self, shutdown_event: asyncio.Event) -> None:
        """
        Set up signal handlers

        Args:
            shutdown_event: Shutdown event
        """
        self._shutdown_event = shutdown_event

        # Signals supported by both Windows and Unix
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Windows-specific signals
        if hasattr(signal, "CTRL_BREAK_EVENT"):
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signal.CTRL_BREAK_EVENT, self._signal_handler)

        if hasattr(signal, "CTRL_C_EVENT"):
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signal.CTRL_C_EVENT, self._signal_handler)

        self._signal_handlers_set = True
        logger.debug("Signal handlers set up")

    def _signal_handler(self, signum, frame):
        """Signal handler"""
        # Prevent duplicate processing
        if self._shutting_down:
            logger.info("Already shutting down, ignoring duplicate signal")
            return

        self._shutting_down = True
        signal_name = signal.Signals(signum).name
        logger.info(f"Received signal {signal_name}, preparing graceful shutdown...")

        # Execute sync cleanup callbacks
        for callback in self._cleanup_callbacks:
            try:
                # For async callbacks, we can only do our best in a sync context
                if asyncio.iscoroutinefunction(callback):
                    logger.warning(
                        "Async cleanup callback cannot be executed in signal handler, skipping"
                    )
                else:
                    callback()
            except Exception as e:
                logger.error(f"Cleanup callback execution failed: {e}")

        logger.info("Resource cleanup complete, exiting process")
        sys.exit(0)

    def register_cleanup_callback(self, callback: Callable) -> None:
        """
        Register a cleanup callback function

        Args:
            callback: Cleanup function
        """
        self._cleanup_callbacks.append(callback)

    async def cleanup_all(self) -> None:
        """Execute all cleanup callbacks"""
        logger.info("Starting resource cleanup...")

        for callback in self._cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Cleanup callback execution failed: {e}")

        logger.info("Resource cleanup complete")

    @property
    def is_shutdown_requested(self) -> bool:
        """Whether shutdown has been requested"""
        return self._shutting_down
