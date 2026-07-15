"""StdioGameBotTransport — JSON-line stdin/stdout transport for game bot runtimes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class StdioGameBotTransport:
    """Transport that communicates with a game bot via newline-delimited JSON over stdio.

    Spawns a subprocess and speaks the same JSON-line protocol currently used by
    MinecraftBridge, but without Minecraft-specific knowledge.
    """

    def __init__(
        self,
        argv: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        *,
        stdout_reader: bool = True,
    ) -> None:
        self._argv = argv
        self._cwd = cwd
        self._env = env
        self._stdout_reader = stdout_reader
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._event_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._running = False

    async def start(self, login_timeout: float = 15.0) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *self._argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
        )
        self._running = True
        if self._stdout_reader:
            self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def stop(self) -> None:
        self._running = False
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError):
                pass

        # Cancel reader tasks
        for task in [self._reader_task, self._stderr_task]:
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        # Cancel pending futures
        for future in self._pending.values():
            if not future.done():
                future.set_exception(asyncio.CancelledError("Transport stopped"))
        self._pending.clear()
        self._process = None

    async def send_command(
        self, action: str, params: dict[str, Any], timeout: float = 60.0
    ) -> dict[str, Any]:
        if not self._process or not self._process.stdin:
            return {"status": "error", "result": f"Action '{action}' failed: transport not started"}

        cmd_id = self._next_id
        self._next_id += 1
        timeout_ms = int(timeout * 1000)

        line = (
            json.dumps({"id": cmd_id, "action": action, "params": params, "timeout_ms": timeout_ms})
            + "\n"
        )

        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[cmd_id] = future

        try:
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
        except (BrokenPipeError, OSError) as exc:
            self._pending.pop(cmd_id, None)
            return {"status": "error", "result": f"Action '{action}' failed: {exc}"}

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._pending.pop(cmd_id, None)
            return {"status": "error", "result": f"Action '{action}' timed out after {timeout}s"}
        except asyncio.CancelledError:
            self._pending.pop(cmd_id, None)
            return {"status": "error", "result": f"Action '{action}' cancelled"}

    def on_event(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._event_callbacks.append(callback)

    @property
    def is_running(self) -> bool:
        return self._running and self._process is not None and self._process.returncode is None

    async def _read_stdout(self) -> None:
        """Read JSON lines from stdout and dispatch to pending futures or event callbacks."""
        if not self._process or not self._process.stdout:
            return
        try:
            while self._running:
                line_bytes = await self._process.stdout.readline()
                if not line_bytes:
                    # EOF — process exited
                    self._cancel_all_pending("Process exited (EOF)")
                    break

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    logger.warning("Malformed JSON from runtime: %s", line[:200])
                    continue

                status = data.get("status")
                cmd_id = data.get("id")

                if status == "event" and (cmd_id is None or cmd_id == "system"):
                    # Async event — dispatch to callbacks
                    result = data.get("result", {})
                    for cb in self._event_callbacks:
                        try:
                            cb(result)
                        except Exception:
                            logger.exception("Event callback error")
                elif cmd_id is not None and cmd_id in self._pending:
                    # Command response — resolve future
                    future = self._pending.pop(cmd_id)
                    if not future.done():
                        future.set_result(
                            {
                                "status": status,
                                "result": data.get("result"),
                            }
                        )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("stdout reader error")
        finally:
            self._cancel_all_pending("Reader stopped")

    async def _read_stderr(self) -> None:
        """Log stderr output from the runtime."""
        if not self._process or not self._process.stderr:
            return
        try:
            while self._running:
                line_bytes = await self._process.stderr.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if line:
                    logger.warning("MC Bot: %s", line)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("stderr reader error", exc_info=True)

    def _cancel_all_pending(self, reason: str) -> None:
        for cmd_id, future in list(self._pending.items()):
            if not future.done():
                future.set_result({"status": "error", "result": reason})
        self._pending.clear()
