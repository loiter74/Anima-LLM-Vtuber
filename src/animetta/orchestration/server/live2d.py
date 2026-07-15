"""
Live2D action queue management
Manages Live2D action queuing and execution
"""

from collections.abc import Callable
from typing import Any

from loguru import logger

from animetta.services.live2d.action_queue import ActionMessage, Live2DActionQueue


class Live2DManager:
    """
    Live2D manager

    Responsibilities:
    1. Manage the Live2D action queue
    2. Execute actions and broadcast to clients
    """

    def __init__(self):
        self._action_queue = None
        self._execute_callback: Callable | None = None

    @property
    def action_queue(self):
        """Get the Live2D action queue (lazy initialization)"""
        if self._action_queue is None:
            self._action_queue = Live2DActionQueue()
            logger.info("[Live2D] Action queue initialized")

        return self._action_queue

    def set_execute_callback(self, callback: Callable[[Any], None]) -> None:
        """
        Set action execution callback

        Args:
            callback: Async callback function, receives ActionMessage parameter
        """
        self._execute_callback = callback

        if self._action_queue:
            self._action_queue.set_execute_callback(callback)
            logger.info("[Live2D] Action execution callback set")

    async def enqueue_action(
        self,
        action_data: dict,
        action_id: str = "",
        queue_policy: str = "append",
        duration: float = 0.5,
    ) -> dict:
        """
        Enqueue an action

        Args:
            action_data: Action data
            action_id: Action ID
            queue_policy: Queue policy ("append", "replace", "immediate")
            duration: Duration in seconds

        Returns:
            dict: Enqueue result
        """

        action = ActionMessage(
            action_id=action_id,
            action=action_data,
            duration_sec=duration,
            queue_policy=queue_policy,
        )

        result = await self.action_queue.enqueue(action)
        logger.info(f"[Live2D] Action enqueued: {action_id}, result: {result}")

        return result

    def is_initialized(self) -> bool:
        """Check if the action queue is initialized"""
        return self._action_queue is not None
