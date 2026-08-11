"""Bounded loopback harness for real Minecraft broadcast review."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

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
    async def start(
        self,
        *,
        profile: str | None,
        request_id: str,
        allow_server_create: bool = False,
    ) -> dict[str, Any]: ...

    async def shutdown_runtime(self, *, request_id: str) -> dict[str, Any]: ...

    async def send_command(
        self, action: str, params: dict[str, Any] | None = None, timeout: float = 60.0
    ) -> dict[str, Any]: ...

    def set_viewer_callback(self, callback: Callable[[str, object], None]) -> None: ...


DEFAULT_VIEWER_WAIT_SECONDS = 10 * 60
IRON_RUN_TIMEOUT_SECONDS = 35 * 60
IRON_RUN_COMMAND_GRACE_SECONDS = 30


class MinecraftGameplayReviewHarness:
    """Coordinate server, bridge, confirmed viewer binding, and iron run."""

    def __init__(
        self,
        *,
        token: str,
        artifact_dir: Path,
        bridge: ReviewBridge,
        profile: str = "managed-review",
        allow_managed_server_create: bool = False,
        viewer_timeout_seconds: float = DEFAULT_VIEWER_WAIT_SECONDS,
    ) -> None:
        self._token = token
        self._artifact_dir = artifact_dir.resolve()
        self._bridge = bridge
        self._profile = profile
        self._allow_managed_server_create = allow_managed_server_create
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
        self._bridge.set_viewer_callback(self._on_viewer_event)
        result = await self._bridge.start(
            profile=self._profile,
            request_id=f"review-connect-{uuid4().hex}",
            allow_server_create=self._allow_managed_server_create,
        )
        if result.get("state") != "ready":
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
                await self._bridge.shutdown_runtime(request_id=f"review-shutdown-{uuid4().hex}")
        finally:
            self._prepared = False


def create_real_harness(
    *,
    repository_dir: Path,
    token: str,
    artifact_dir: Path,
    viewer_timeout_seconds: float = DEFAULT_VIEWER_WAIT_SECONDS,
    allow_managed_server_create: bool = False,
) -> MinecraftGameplayReviewHarness:
    """Create a review harness that delegates all runtime ownership to mc-mcp."""
    from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge
    from animetta.tools.minecraft.core.config import MinecraftConfig

    del repository_dir
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    return MinecraftGameplayReviewHarness(
        token=token,
        artifact_dir=artifact_dir,
        bridge=bridge,
        profile="managed-review",
        allow_managed_server_create=allow_managed_server_create,
        viewer_timeout_seconds=viewer_timeout_seconds,
    )


def _error_response(exc: MinecraftReviewError) -> JSONResponse:
    category = str(exc)
    status = {
        "authentication": 401,
        "busy": 409,
        "viewer_timeout": 408,
        "not_ready": 503,
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
