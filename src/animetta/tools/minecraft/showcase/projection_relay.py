"""Local Socket.IO relay for the real showcase StageProjector output."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any, Protocol

import socketio
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles


class SocketEmitter(Protocol):
    async def emit(
        self,
        event: str,
        payload: dict[str, Any],
        to: str | None = None,
    ) -> None: ...


class ProjectionSocketRelay:
    """Broadcast projections and replay the same immutable envelopes on reconnect."""

    def __init__(self, socket_server: SocketEmitter, *, maximum_events: int = 10_000) -> None:
        self._socket_server = socket_server
        self._maximum_events = maximum_events
        self._events: dict[str, dict[str, Any]] = {}

    async def emit(self, payload: dict[str, Any]) -> None:
        event = payload.get("event")
        event_id = payload.get("event_id")
        projection_kind = payload.get("projection_kind")
        if (
            not isinstance(event, str)
            or not event.startswith("minecraft.")
            or not event.endswith(".projection")
            or not isinstance(event_id, str)
            or not event_id
            or not isinstance(projection_kind, str)
            or not projection_kind
        ):
            raise ValueError("SHOWCASE_PROJECTION_EVENT_INVALID")
        detached = dict(payload)
        self._events[event_id] = detached
        while len(self._events) > self._maximum_events:
            self._events.pop(next(iter(self._events)))
        await self._socket_server.emit(event, detached)

    async def replay(self, sid: str) -> None:
        for payload in tuple(self._events.values()):
            await self._socket_server.emit(str(payload["event"]), dict(payload), to=sid)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class ShowcaseProjectionServer:
    """Serve the built gameplay page and its live projection socket locally."""

    def __init__(
        self,
        *,
        relay: ProjectionSocketRelay,
        server: uvicorn.Server,
        task: asyncio.Task[None],
        host: str,
        port: int,
    ) -> None:
        self.relay = relay
        self._server = server
        self._task = task
        self.host = host
        self.port = port

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def walkthrough_url(self, run_id: str) -> str:
        return f"{self.base_url}/minecraft-gameplay.html?runId={run_id}"

    @classmethod
    async def start(
        cls,
        *,
        frontend_dist: Path,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> ShowcaseProjectionServer:
        static_root = frontend_dist.resolve()
        if not (static_root / "minecraft-gameplay.html").is_file():
            raise RuntimeError("SHOWCASE_FRONTEND_BUILD_MISSING")
        bound_port = port or _free_loopback_port()
        sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])
        relay = ProjectionSocketRelay(sio)

        async def connect(sid: str, _environ: dict[str, Any], _auth: object) -> None:
            await relay.replay(sid)

        sio.on("connect", handler=connect)

        async def health(_request: object) -> JSONResponse:
            return JSONResponse({"status": "ok", "service": "showcase-projection"})

        async def root(_request: object) -> RedirectResponse:
            return RedirectResponse("/minecraft-gameplay.html")

        static = StaticFiles(directory=static_root, html=True)
        starlette = Starlette(
            routes=[
                Route("/health", health),
                Route("/", root),
                Mount("/", app=static),
            ]
        )
        app = socketio.ASGIApp(sio, other_asgi_app=starlette, socketio_path="socket.io")
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=bound_port,
                log_level="warning",
                access_log=False,
            )
        )
        task = asyncio.create_task(server.serve(), name="showcase-projection-server")
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("SHOWCASE_PROJECTION_SERVER_EXITED")
                    await asyncio.sleep(0.05)
        except BaseException:
            server.should_exit = True
            await asyncio.gather(task, return_exceptions=True)
            raise
        return cls(
            relay=relay,
            server=server,
            task=task,
            host=host,
            port=bound_port,
        )

    async def close(self) -> None:
        self._server.should_exit = True
        await self._task
