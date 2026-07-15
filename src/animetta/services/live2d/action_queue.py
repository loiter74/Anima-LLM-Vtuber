from __future__ import annotations

"""
Live2D Action Queue
Manages the action queue for Live2D models, based on open-yachiyo implementation
"""

import asyncio
import contextlib
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from loguru import logger


class OverflowPolicy(Enum):
    """Queue overflow policy"""

    DROP_OLDEST = "drop_oldest"  # Drop the oldest
    DROP_NEWEST = "drop_newest"  # Drop the newest
    REJECT = "reject"  # Reject new actions


class QueuePolicy(Enum):
    """Action queue policy"""

    APPEND = "append"  # Append to the end of the queue
    REPLACE = "replace"  # Clear the queue and execute the new action
    INTERRUPT = "interrupt"  # Immediately interrupt the current action and execute the new action


@dataclass
class ActionMessage:
    """Action message"""

    action_id: str
    action: dict
    duration_sec: float = 0.5
    queue_policy: str = "append"

    def __post_init__(self):
        if isinstance(self.queue_policy, str):
            self.queue_policy = QueuePolicy(self.queue_policy)


class Live2DActionMutex:
    """
    Live2D Action Mutex

    Ensures only one action executes at a time,
    prevents action conflicts (e.g., playing multiple motions simultaneously)
    """

    def __init__(self, cooldown_ms: int = 250):
        self.cooldown_ms = cooldown_ms
        self._last_action_end: float = 0
        self._is_executing: bool = False
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Acquire the mutex lock"""
        async with self._lock:
            # Check cooldown time
            elapsed_ms = (time.time() - self._last_action_end) * 1000
            if elapsed_ms < self.cooldown_ms:
                await asyncio.sleep((self.cooldown_ms - elapsed_ms) / 1000)

            # Check if executing
            if self._is_executing:
                return False

            self._is_executing = True
            return True

    async def release(self):
        """Release the mutex lock"""
        async with self._lock:
            self._is_executing = False
            self._last_action_end = time.time()


class Live2DActionQueue:
    """
    Live2D Action Queue

    Features:
    1. Manage action queue (FIFO)
    2. Handle queue overflow
    3. Action mutex lock
    4. Execute actions asynchronously
    """

    def __init__(
        self,
        max_size: int = 120,
        overflow_policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
        mutex: Live2DActionMutex | None = None,
    ):
        self.max_size = max_size
        self.overflow_policy = overflow_policy
        self.queue: list[ActionMessage] = []
        self.mutex = mutex or Live2DActionMutex()

        # Execution state
        self._is_processing = False
        self._current_action: ActionMessage | None = None

        # Action execution callback
        self._execute_callback: callable | None = None

        # Task tracking (for cleanup)
        self._process_task: asyncio.Task | None = None

    def set_execute_callback(self, callback: callable):
        """Set action execution callback"""
        self._execute_callback = callback

    async def enqueue(self, action: ActionMessage) -> dict[str, Any]:
        """
        Enqueue action

        Args:
            action: Action message

        Returns:
            Operation result
        """
        # Handle queue policy
        if isinstance(action.queue_policy, str):
            action.queue_policy = QueuePolicy(action.queue_policy)

        if action.queue_policy == QueuePolicy.REPLACE:
            # Clear the queue
            self.queue.clear()
            # Interrupt current action
            if self._is_processing:
                await self._interrupt_current()

        elif action.queue_policy == QueuePolicy.INTERRUPT:
            # Clear the queue and interrupt current action
            self.queue.clear()
            if self._is_processing:
                await self._interrupt_current()

        # Check if queue is full
        if len(self.queue) >= self.max_size:
            if self.overflow_policy == OverflowPolicy.DROP_OLDEST:
                self.queue.pop(0)
                logger.debug("[ActionQueue] Queue full, dropping oldest action")
            elif self.overflow_policy == OverflowPolicy.DROP_NEWEST:
                return {"ok": False, "reason": "queue_overflow"}
            elif self.overflow_policy == OverflowPolicy.REJECT:
                return {"ok": False, "reason": "queue_full"}

        # Enqueue
        self.queue.append(action)
        logger.debug(
            f"[ActionQueue] Action enqueued: {action.action_id}, queue length: {len(self.queue)}"
        )

        # Start processing
        if not self._is_processing:
            self._process_task = asyncio.create_task(self._process_queue())
            # Add error handling
            self._process_task.add_done_callback(self._handle_task_exception)

        return {"ok": True, "queue_size": len(self.queue)}

    async def _interrupt_current(self):
        """Interrupt the current action"""
        if self._current_action:
            logger.info(f"[ActionQueue] Interrupting action: {self._current_action.action_id}")
            # TODO: Notify client to interrupt current action
        await self.mutex.release()
        self._is_processing = False
        self._current_action = None

    async def _process_queue(self):
        """Process actions in the queue"""
        if self._is_processing:
            return

        self._is_processing = True

        try:
            while self.queue:
                # Get the next action
                action = self.queue.pop(0)
                self._current_action = action

                # Wait for mutex lock
                acquired = await self.mutex.acquire()
                if not acquired:
                    logger.warning(
                        f"[ActionQueue] Cannot acquire mutex, skipping action: {action.action_id}"
                    )
                    continue

                try:
                    # Execute action
                    logger.info(
                        f"[ActionQueue] Executing action: {action.action_id}, type: {action.action.get('type')}"
                    )
                    await self._execute_action(action)

                    # Wait for action completion
                    await asyncio.sleep(action.duration_sec)

                finally:
                    # Release the mutex lock
                    await self.mutex.release()

        finally:
            self._is_processing = False
            self._current_action = None

    async def _execute_action(self, action: ActionMessage):
        """Execute a single action"""
        if self._execute_callback:
            await self._execute_callback(action)
        else:
            logger.warning(
                f"[ActionQueue] No execute callback set, action not executed: {action.action_id}"
            )

    def _handle_task_exception(self, task: asyncio.Task):
        """Handle task exceptions (prevent task leaks)"""
        try:
            # If the task has an exception, re-raise it here
            exception = task.exception()
            if exception:
                logger.error(f"[ActionQueue] Task exception: {exception}", exc_info=exception)
        except asyncio.CancelledError:
            logger.debug("[ActionQueue] Task was cancelled")
        except Exception as e:
            logger.error(f"[ActionQueue] Error handling task exception: {e}", exc_info=e)

    async def stop(self):
        """Stop queue processing and clean up resources"""
        # Cancel the running task
        if self._process_task and not self._process_task.done():
            self._process_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._process_task

        # Clear the queue
        self.queue.clear()
        self._is_processing = False
        self._current_action = None
        logger.debug("[ActionQueue] Queue stopped")

    def clear(self):
        """Clear the queue"""
        self.queue.clear()
        logger.debug("[ActionQueue] Queue cleared")

    @property
    def queue_size(self) -> int:
        """Get queue size"""
        return len(self.queue)

    @property
    def is_processing(self) -> bool:
        """Whether processing is active"""
        return self._is_processing

    @property
    def current_action(self) -> ActionMessage | None:
        """Get the current executing action"""
        return self._current_action


# ==================== Action Factory ====================


class ActionFactory:
    """Action message factory"""

    @staticmethod
    def expression(expression_name: str, intensity: str = "medium") -> ActionMessage:
        """Create an expression action"""
        return ActionMessage(
            action_id=f"expr_{expression_name}_{intensity}_{time.time()}",
            action={"type": "expression", "name": expression_name, "intensity": intensity},
            duration_sec=0.3,
        )

    @staticmethod
    def motion(group: str, index: int, expression: str = None) -> ActionMessage:
        """Create a motion action"""
        action_data = {"type": "motion", "group": group, "index": index}
        if expression:
            action_data["expression"] = expression

        return ActionMessage(
            action_id=f"motion_{group}_{index}_{time.time()}", action=action_data, duration_sec=1.0
        )

    @staticmethod
    def param(param_name: str, value: float) -> ActionMessage:
        """Create a parameter action"""
        return ActionMessage(
            action_id=f"param_{param_name}_{value}_{time.time()}",
            action={"type": "param", "name": param_name, "value": value},
            duration_sec=0.1,
        )

    @staticmethod
    def sequence(actions: list[dict], total_duration: float) -> ActionMessage:
        """Create a sequence action"""
        return ActionMessage(
            action_id=f"seq_{time.time()}",
            action={"type": "sequence", "actions": actions},
            duration_sec=total_duration,
        )
