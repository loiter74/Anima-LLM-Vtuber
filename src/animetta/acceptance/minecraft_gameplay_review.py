"""Bounded loopback harness for real Minecraft broadcast review."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route


class MinecraftReviewError(RuntimeError):
    """Sanitized review failure with a low-cardinality reason."""

    def __init__(self, category: str, *, details: dict[str, str] | None = None) -> None:
        super().__init__(category)
        self.details = details or {}


class ReviewBridge(Protocol):
    async def start(self) -> bool: ...

    async def stop(self) -> None: ...

    async def send_command(
        self, action: str, params: dict[str, Any] | None = None, timeout: float = 60.0
    ) -> dict[str, Any]: ...

    def set_viewer_callback(self, callback: Callable[[str, object], None]) -> None: ...


class ReviewServer(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


CommandRunner = Callable[[list[str], dict[str, str]], Awaitable[str | None]]
ReadinessProbe = Callable[[], Awaitable[bool]]
Sleeper = Callable[[float], Awaitable[None]]

SERVER_READINESS_ATTEMPTS = 240
SERVER_READINESS_INTERVAL_SECONDS = 2.0
DEFAULT_VIEWER_WAIT_SECONDS = 10 * 60
IRON_RUN_TIMEOUT_SECONDS = 35 * 60
IRON_RUN_COMMAND_GRACE_SECONDS = 30


def _encode_varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        encoded.append(byte)
        if not value:
            return bytes(encoded)


async def _read_varint(reader: asyncio.StreamReader) -> int:
    value = 0
    for shift in range(0, 35, 7):
        byte = (await reader.readexactly(1))[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
    raise ValueError("varint_too_large")


async def _run_command(args: list[str], env: dict[str, str]) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        env={**os.environ, **env},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        output = (stderr or stdout).decode("utf-8", errors="replace")[-2_000:]
        raise MinecraftReviewError(f"compose_failed:{output}")
    return stdout.decode("utf-8", errors="replace").strip()


async def _probe_review_server() -> bool:
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 25566), timeout=1.0
        )
        host = b"127.0.0.1"
        handshake = (
            b"\x00"
            + _encode_varint(767)
            + _encode_varint(len(host))
            + host
            + (25566).to_bytes(2, "big")
            + b"\x01"
        )
        writer.write(_encode_varint(len(handshake)) + handshake + b"\x01\x00")
        await writer.drain()
        packet_length = await asyncio.wait_for(_read_varint(reader), timeout=1.0)
        if packet_length <= 1:
            return False
        packet_id = await asyncio.wait_for(_read_varint(reader), timeout=1.0)
        return packet_id == 0
    except (OSError, TimeoutError, asyncio.IncompleteReadError, ValueError):
        return False
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()


def _offline_player_uuid(username: str) -> str:
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode()).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(digest)))


def _runtime_copy_path(path: Path) -> str | Path:
    """Allow a copied runtime tree to contain paths beyond legacy MAX_PATH."""

    if os.name != "nt":
        return path
    raw = str(path.resolve())
    if raw.startswith("\\\\?\\"):
        return raw
    if raw.startswith("\\\\"):
        return f"\\\\?\\UNC\\{raw[2:]}"
    return f"\\\\?\\{raw}"


class MinecraftReviewServerLease:
    """Own an isolated Compose project and disposable bind-mounted world."""

    _RUNTIME_SEED_FILES = (
        "paper-1.21-130.jar",
        ".paper.env",
        ".papermc-manifest.json",
        ".modrinth-manifest.json",
        "cache/mojang_1.21.jar",
        "plugins/spectatorplus-paper-1.2.1.jar",
        "config/paper-global.yml",
        "config/paper-world-defaults.yml",
        "bukkit.yml",
        "spigot.yml",
    )
    _RUNTIME_SEED_DIRECTORIES = ("libraries", "versions")

    def __init__(
        self,
        *,
        repository_dir: Path,
        world_dir: Path,
        world_seed: int = -1_334_312_645,
        runtime_seed_dir: Path | None = None,
        run_command: CommandRunner = _run_command,
        readiness_probe: ReadinessProbe = _probe_review_server,
        readiness_attempts: int = SERVER_READINESS_ATTEMPTS,
        readiness_interval_seconds: float = SERVER_READINESS_INTERVAL_SECONDS,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        if readiness_attempts < 1:
            raise ValueError("readiness_attempts must be positive")
        if readiness_interval_seconds <= 0:
            raise ValueError("readiness_interval_seconds must be positive")
        self.repository_dir = repository_dir.resolve()
        self.world_dir = world_dir.resolve()
        self.world_seed = world_seed
        canonical_repository = (
            self.repository_dir.parent.parent
            if self.repository_dir.parent.name == ".worktrees"
            else self.repository_dir
        )
        self.runtime_seed_dir = (
            runtime_seed_dir.resolve()
            if runtime_seed_dir is not None
            else canonical_repository / "docker" / "minecraft-server" / "data"
        )
        self._run_command = run_command
        self._readiness_probe = readiness_probe
        self._readiness_attempts = readiness_attempts
        self._readiness_interval_seconds = readiness_interval_seconds
        self._sleep = sleep
        self._started = False
        self._closed = False
        self._compose_file = (
            self.repository_dir / "docker" / "minecraft-server" / "docker-compose.review.yml"
        )

    def _compose(self, *args: str) -> list[str]:
        return [
            "docker",
            "compose",
            "-p",
            "animetta-mc-review",
            "-f",
            str(self._compose_file),
            *args,
        ]

    def _environment(self) -> dict[str, str]:
        return {
            "ANIMETTA_MC_REVIEW_PORT": "25566",
            "ANIMETTA_MC_REVIEW_WORLD_DIR": str(self.world_dir),
            "ANIMETTA_MC_REVIEW_SEED": str(self.world_seed),
        }

    async def execute_rcon(self, command: str) -> str:
        """Execute one pre-authorized setup command against the owned server."""

        if not self._started or self._closed:
            raise MinecraftReviewError("server_not_ready")
        response = await self._run_command(
            self._compose("exec", "-T", "minecraft", "rcon-cli", command),
            self._environment(),
        )
        return str(response or "").strip()

    async def start(self) -> None:
        if self._started:
            return
        self.world_dir.mkdir(parents=True, exist_ok=True)
        self._seed_runtime()
        (self.world_dir / "ops.json").write_text(
            json.dumps(
                [
                    {
                        "uuid": _offline_player_uuid("AnimettaBot"),
                        "name": "AnimettaBot",
                        "level": 4,
                        "bypassesPlayerLimit": True,
                    }
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        await self._run_command(self._compose("up", "-d"), self._environment())
        self._started = True
        for _ in range(self._readiness_attempts):
            if await self._readiness_probe():
                await self._run_command(
                    self._compose(
                        "exec",
                        "-T",
                        "minecraft",
                        "rcon-cli",
                        "gamerule spawnRadius 0",
                    ),
                    self._environment(),
                )
                return
            await self._sleep(self._readiness_interval_seconds)
        await self.stop()
        raise MinecraftReviewError("server_timeout")

    def _seed_runtime(self) -> None:
        if not self.runtime_seed_dir.is_dir():
            return
        for relative_name in self._RUNTIME_SEED_FILES:
            source = self.runtime_seed_dir / relative_name
            if not source.is_file():
                continue
            target = self.world_dir / relative_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for relative_name in self._RUNTIME_SEED_DIRECTORIES:
            source = self.runtime_seed_dir / relative_name
            if source.is_dir():
                shutil.copytree(
                    _runtime_copy_path(source),
                    _runtime_copy_path(self.world_dir / relative_name),
                    dirs_exist_ok=True,
                )

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._started:
            await self._run_command(
                self._compose("down", "--volumes", "--remove-orphans"),
                self._environment(),
            )
        self._started = False
        shutil.rmtree(self.world_dir, ignore_errors=True)


class MinecraftGameplayReviewHarness:
    """Coordinate server, bridge, confirmed viewer binding, and iron run."""

    def __init__(
        self,
        *,
        token: str,
        artifact_dir: Path,
        server: ReviewServer,
        bridge: ReviewBridge,
        viewer_timeout_seconds: float = DEFAULT_VIEWER_WAIT_SECONDS,
    ) -> None:
        self._token = token
        self._artifact_dir = artifact_dir.resolve()
        self._server = server
        self._bridge = bridge
        self._viewer_timeout_seconds = viewer_timeout_seconds
        self._prepared = False
        self._closed = False
        self._run_lock = asyncio.Lock()
        self._following = asyncio.Event()
        self._binding: dict[str, Any] = {
            "binding_state": "waiting",
            "confirmed": False,
            "username": "LUN077",
            "target": "AnimettaBot",
            "attempt": 0,
            "reason": "viewer_offline",
        }

    def _authorize(self, authorization: str) -> None:
        expected = f"Bearer {self._token}"
        if not hmac.compare_digest(authorization, expected):
            raise MinecraftReviewError("authentication")

    def authorize(self, authorization: str) -> None:
        self._authorize(authorization)

    def _on_viewer_event(self, event_type: str, payload: object) -> None:
        if event_type != "client_viewer_status" or not isinstance(payload, dict):
            return
        state = payload.get("binding_state", payload.get("state", "waiting"))
        if state not in {"disabled", "waiting", "attaching", "following", "degraded"}:
            state = "degraded"
        confirmed = state == "following" and payload.get("confirmed") is True
        reason = payload.get("reason")
        allowed_reasons = {
            "disabled",
            "viewer_offline",
            "viewer_joined",
            "bot_spawn",
            "bot_respawn",
            "dimension_change",
            "manual_retry",
            "periodic_check",
            "confirmation_timeout",
            "confirmation_rejected",
            "command_failed",
            "closed",
            "config_missing",
            "unknown",
        }
        self._binding = {
            "binding_state": state,
            "confirmed": confirmed,
            "username": str(payload.get("username", ""))[:32],
            "target": str(payload.get("target", "AnimettaBot"))[:32],
            "attempt": max(0, int(payload.get("attempt", 0) or 0)),
            "reason": reason if reason in allowed_reasons else "unknown",
        }
        retry_in_ms = payload.get("retry_in_ms")
        if isinstance(retry_in_ms, int) and retry_in_ms >= 0:
            self._binding["retry_in_ms"] = retry_in_ms
        if confirmed:
            self._following.set()
        else:
            self._following.clear()

    async def prepare(self) -> None:
        if self._prepared:
            return
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        await self._server.start()
        self._bridge.set_viewer_callback(self._on_viewer_event)
        if not await self._bridge.start():
            await self._server.stop()
            raise MinecraftReviewError("bridge_start_failed")
        self._prepared = True

    def readiness(self) -> dict[str, Any]:
        return {
            "ready": self._prepared and not self._closed,
            "binding": dict(self._binding),
        }

    async def run(self, *, authorization: str) -> dict[str, Any]:
        self._authorize(authorization)
        if not self._prepared or self._closed:
            raise MinecraftReviewError("not_ready")
        if self._run_lock.locked():
            raise MinecraftReviewError("busy")
        async with self._run_lock:
            try:
                async with asyncio.timeout(self._viewer_timeout_seconds):
                    await self._following.wait()
            except TimeoutError as exc:
                raise MinecraftReviewError("viewer_timeout") from exc
            response = await self._bridge.send_command(
                "survival_iron",
                {"timeout_ms": IRON_RUN_TIMEOUT_SECONDS * 1_000},
                timeout=IRON_RUN_TIMEOUT_SECONDS + IRON_RUN_COMMAND_GRACE_SECONDS,
            )
            report = response.get("result") if response.get("status") == "success" else None
            if not isinstance(report, dict):
                raise MinecraftReviewError("iron_run_failed")
            gear = report.get("iron_gear_achieved")
            iron_gear_complete = (
                isinstance(gear, dict)
                and bool(gear)
                and all(value is True for value in gear.values())
            )
            if report.get("completed") is not True or not iron_gear_complete:
                failed_phase = next(
                    (
                        phase
                        for phase in report.get("phase_results", [])
                        if isinstance(phase, dict) and phase.get("success") is not True
                    ),
                    {},
                )
                phase = str(failed_phase.get("phase", "unknown"))
                if phase not in {
                    "wood",
                    "crafting_table",
                    "wooden_pickaxe",
                    "cobblestone",
                    "stone_kit",
                    "fuel",
                    "iron_ore",
                    "smelt_iron",
                    "iron_gear",
                }:
                    phase = "unknown"
                failure_category = str(failed_phase.get("failure_category", "incomplete"))
                if failure_category not in {"action_failed", "timeout", "incomplete"}:
                    failure_category = "unknown"
                failure_code = str(failed_phase.get("failure_code", "UNKNOWN"))
                if failure_code not in {
                    "NO_CRAFTING_TABLE",
                    "MISSING_MATERIALS",
                    "CRAFT_FAILED",
                    "NO_RECIPE",
                    "COLLECT_FAILED",
                    "PARTIAL_COLLECT",
                    "SMELT_FAILED",
                    "EQUIP_FAILED",
                    "UNSUPPORTED_ACTION",
                    "UNKNOWN",
                }:
                    failure_code = "UNKNOWN"
                failure_item = str(failed_phase.get("failure_item", "unknown"))
                if failure_item not in {
                    "oak_planks",
                    "stick",
                    "cobblestone",
                    "coal",
                    "iron_ingot",
                }:
                    failure_item = "unknown"
                missing_count = failed_phase.get("missing_count", 0)
                final_inventory = report.get("final_inventory", {})
                if not isinstance(final_inventory, dict):
                    final_inventory = {}
                safe_material_counts = {
                    f"inventory_{name}": str(
                        min(64, max(0, int(final_inventory.get(name, 0) or 0)))
                    )
                    for name in ("oak_log", "oak_planks", "stick", "crafting_table")
                }
                raise MinecraftReviewError(
                    "iron_run_incomplete",
                    details={
                        "phase": phase,
                        "failure_category": failure_category,
                        "failure_code": failure_code,
                        "failure_item": failure_item,
                        "missing_count": str(min(64, max(0, int(missing_count or 0)))),
                        **safe_material_counts,
                    },
                )

            safe_report = {
                "completed": True,
                "elapsed_seconds": float(report.get("elapsed_seconds", 0)),
                "deaths": max(0, int(report.get("deaths", 0) or 0)),
                "iron_gear_complete": True,
                "iron_gear_achieved": {
                    str(name)[:64]: value is True for name, value in gear.items()
                },
                "phase_results": [
                    {
                        "phase": str(phase.get("phase", ""))[:64],
                        "success": phase.get("success") is True,
                        "actions_attempted": max(0, int(phase.get("actions_attempted", 0) or 0)),
                        "actions_succeeded": max(0, int(phase.get("actions_succeeded", 0) or 0)),
                        "failure_category": (
                            str(phase.get("failure_category"))[:64]
                            if phase.get("failure_category")
                            else None
                        ),
                    }
                    for phase in report.get("phase_results", [])
                    if isinstance(phase, dict)
                ],
            }
            report_name = "survival-iron-report.json"
            (self._artifact_dir / report_name).write_text(
                json.dumps(safe_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {
                "binding": dict(self._binding),
                "report": safe_report,
                "gameplay_report": f"/artifacts/{report_name}",
            }

    def artifact_path(self, value: str) -> Path | None:
        name = Path(value).name
        if not name or name != value.removeprefix("/artifacts/"):
            return None
        candidate = (self._artifact_dir / name).resolve()
        if candidate.parent != self._artifact_dir:
            return None
        return candidate

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._prepared:
                await self._bridge.stop()
        finally:
            self._prepared = False
            await self._server.stop()


def resolve_external_runtime_dir(repository_dir: Path) -> Path:
    repository_dir = repository_dir.resolve()
    canonical_repository = (
        repository_dir.parent.parent
        if repository_dir.parent.name == ".worktrees"
        else repository_dir
    )
    return canonical_repository.parent / "voyager-mc-bot"


def create_real_harness(
    *,
    repository_dir: Path,
    token: str,
    artifact_dir: Path,
    viewer_timeout_seconds: float = DEFAULT_VIEWER_WAIT_SECONDS,
) -> MinecraftGameplayReviewHarness:
    """Create the Windows/Docker/Desktop real-runtime harness."""
    from animetta.tools.minecraft.core.bridge import MinecraftBridge
    from animetta.tools.minecraft.core.config import (
        MinecraftBotConfig,
        MinecraftClientViewerConfig,
        MinecraftConfig,
        MinecraftRuntimeConfig,
    )

    repository_dir = repository_dir.resolve()
    runtime_dir = resolve_external_runtime_dir(repository_dir)
    server = MinecraftReviewServerLease(
        repository_dir=repository_dir,
        world_dir=artifact_dir / "_world",
    )
    bridge = MinecraftBridge(
        MinecraftConfig(
            enabled=True,
            bot=MinecraftBotConfig(
                host="127.0.0.1",
                port=25566,
                username="AnimettaBot",
                version="1.21",
            ),
            client_viewer=MinecraftClientViewerConfig(
                enabled=True,
                username="LUN077",
                auto_spectate=True,
                poll_interval=20,
                spectate_timeout=8,
            ),
            runtime=MinecraftRuntimeConfig(
                runtime_path=str(runtime_dir),
                entrypoint="src/index.js",
                package_manager="npm",
                use_embedded_fallback=False,
            ),
        )
    )
    return MinecraftGameplayReviewHarness(
        token=token,
        artifact_dir=artifact_dir,
        server=server,
        bridge=bridge,
        viewer_timeout_seconds=viewer_timeout_seconds,
    )


def _error_response(exc: MinecraftReviewError) -> JSONResponse:
    category = str(exc)
    status = {
        "authentication": 401,
        "busy": 409,
        "viewer_timeout": 408,
        "not_ready": 503,
        "server_timeout": 503,
        "bridge_start_failed": 503,
        "iron_run_failed": 502,
        "iron_run_incomplete": 422,
    }.get(category, 500)
    safe_category = (
        category
        if category
        in {
            "authentication",
            "busy",
            "viewer_timeout",
            "not_ready",
            "server_timeout",
            "bridge_start_failed",
            "iron_run_failed",
            "iron_run_incomplete",
        }
        else "review_error"
    )
    payload = {"category": safe_category}
    if safe_category == "iron_run_incomplete":
        payload.update(exc.details)
    return JSONResponse(payload, status_code=status)


def create_review_app(harness: MinecraftGameplayReviewHarness) -> Starlette:
    """Expose a loopback-safe authenticated review API."""
    prepare_lock = asyncio.Lock()
    run_task: asyncio.Task[dict[str, Any]] | None = None

    async def cancel_run() -> None:
        nonlocal run_task
        if run_task is not None and not run_task.done():
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_task
        run_task = None

    async def health(request: Request) -> JSONResponse:
        del request
        return JSONResponse({"status": "ok", "service": "minecraft-gameplay-review"})

    async def ready(request: Request) -> JSONResponse:
        try:
            harness.authorize(request.headers.get("authorization", ""))
            async with prepare_lock:
                await harness.prepare()
            return JSONResponse(harness.readiness())
        except MinecraftReviewError as exc:
            return _error_response(exc)

    async def run(request: Request) -> JSONResponse:
        nonlocal run_task
        try:
            authorization = request.headers.get("authorization", "")
            harness.authorize(authorization)
            if request.method == "POST":
                if run_task is not None and not run_task.done():
                    raise MinecraftReviewError("busy")
                run_task = asyncio.create_task(harness.run(authorization=authorization))
            if run_task is None:
                raise MinecraftReviewError("not_ready")
            if not run_task.done():
                return JSONResponse({"status": "running"}, status_code=202)
            result = run_task.result()
            return JSONResponse(result, status_code=200)
        except MinecraftReviewError as exc:
            return _error_response(exc)

    async def artifact(request: Request):
        try:
            harness.authorize(request.headers.get("authorization", ""))
        except MinecraftReviewError as exc:
            return _error_response(exc)
        path = harness.artifact_path(str(request.path_params["name"]))
        if path is None or not path.is_file():
            return JSONResponse({"category": "not_found"}, status_code=404)
        return FileResponse(path, media_type="application/json")

    async def shutdown(request: Request) -> JSONResponse:
        try:
            harness.authorize(request.headers.get("authorization", ""))
            await cancel_run()
            await harness.close()
            return JSONResponse({"closed": True})
        except MinecraftReviewError as exc:
            return _error_response(exc)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        del app
        try:
            yield
        finally:
            await cancel_run()
            await harness.close()

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/ready", ready, methods=["POST"]),
            Route("/v1/review/run", run, methods=["GET", "POST"]),
            Route("/artifacts/{name:str}", artifact, methods=["GET"]),
            Route("/shutdown", shutdown, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
