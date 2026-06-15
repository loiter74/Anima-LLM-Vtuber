"""Inspection scheduler — background asyncio.Task for periodic runs."""

from __future__ import annotations

import asyncio

from loguru import logger

from .checks.health import refresh_llm_connectivity_cache
from .inspector import run_full_inspection
from .reporter import send_alert, store_report


class InspectionScheduler:
    """Schedules and runs periodic full inspections.

    Uses asyncio.Task for lifecycle management. Started via
    asyncio.ensure_future() in socketio_server.py during server startup.

    Attributes:
        interval_hours: Hours between inspection runs (default 24).
        connectivity_refresh_minutes: Minutes between LLM connectivity
            cache refreshes (default 10).
        _task: The running asyncio.Task, or None if not started.
        _stop_event: asyncio.Event signalled to stop the loop.
    """

    def __init__(
        self,
        interval_hours: float = 24.0,
        connectivity_refresh_minutes: float = 10.0,
    ) -> None:
        self.interval_hours = interval_hours
        self.connectivity_refresh_minutes = connectivity_refresh_minutes
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background inspection loop.

        Creates an asyncio.Task that runs _loop() indefinitely.
        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._task is not None and not self._task.done():
            logger.warning("[inspection:scheduler] Already running, skipping start")
            return

        self._stop_event.clear()
        self._task = asyncio.ensure_future(self._loop())
        logger.info(
            f"[inspection:scheduler] Started (interval={self.interval_hours}h)"
        )

    async def stop(self) -> None:
        """Stop the background inspection loop gracefully.

        Signals the loop to exit and waits for the task to finish.
        Safe to call if not running.
        """
        if self._task is None or self._task.done():
            return

        logger.info("[inspection:scheduler] Stopping...")
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=30.0)
        except TimeoutError:
            logger.warning(
                "[inspection:scheduler] Task did not stop within 30s, cancelling"
            )
            self._task.cancel()
        logger.info("[inspection:scheduler] Stopped")

    async def _loop(self) -> None:
        """Main inspection loop — runs forever until stop() is called.

        Lifecycle:
          1. Warmup: sleep 10 seconds to let server stabilize.
          2. Connectivity refresh: update LLM API cache every N minutes.
          3. Full inspection: run_full_inspection → store_report →
             (if not ok) send_alert → sleep interval_hours.
        """
        connectivity_seconds = self.connectivity_refresh_minutes * 60
        last_connectivity_refresh = 0.0

        # Warmup delay — let the server finish initializing (model loading, TTS cold start, etc.)
        await asyncio.sleep(120)
        logger.info("[inspection:scheduler] Warmup complete, entering main loop")

        while not self._stop_event.is_set():
            now = asyncio.get_event_loop().time()

            # Periodic LLM connectivity cache refresh (every N minutes)
            if now - last_connectivity_refresh >= connectivity_seconds:
                try:
                    await refresh_llm_connectivity_cache()
                    last_connectivity_refresh = now
                except Exception as exc:
                    logger.warning(
                        f"[inspection:scheduler] Connectivity refresh failed: {exc}"
                    )

            try:

                report = await run_full_inspection()
                await store_report(report)

                if not report.overall_ok:
                    await send_alert(report)

            except Exception as exc:
                logger.error(
                    f"[inspection:scheduler] Inspection loop crashed: {exc}"
                )

            # Sleep until next interval, but check stop_event periodically
            # so stop() does not need to wait the full interval.
            sleep_seconds = self.interval_hours * 3600
            check_interval = min(5.0, sleep_seconds, connectivity_seconds)
            elapsed = 0.0
            while elapsed < sleep_seconds and not self._stop_event.is_set():
                await asyncio.sleep(check_interval)
                elapsed += check_interval
