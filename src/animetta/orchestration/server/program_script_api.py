"""Starlette control plane for program scripts, runs, and danmaku replay."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Match, Route

from animetta.services.command_inbox import CommandDecision, CommandInbox, CommandKey
from animetta.services.program_script import (
    ProgramReplayCoordinator,
    ProgramRuntimeError,
    ProgramScript,
    ProgramScriptRepository,
    ProgramScriptRepositoryError,
    ProgramScriptRunner,
    ReplayCoordinatorError,
    compile_script_events,
    parse_jsonl_events,
)


def get_program_script_routes(
    repository: ProgramScriptRepository,
    runner: ProgramScriptRunner,
    replay: ProgramReplayCoordinator,
    command_inbox: CommandInbox | None = None,
) -> list[BaseRoute]:
    """Build the HTTP routes around injected program-domain services."""

    async def list_scripts(_request: Request) -> JSONResponse:
        return JSONResponse({"scripts": repository.list_scripts()})

    async def create_draft(request: Request) -> JSONResponse:
        body = await _json_body(request)
        draft = repository.create_draft(ProgramScript.model_validate(body.get("script")))
        return JSONResponse(draft.model_dump(mode="json"), status_code=201)

    async def get_draft(request: Request) -> JSONResponse:
        draft = repository.get_draft(request.path_params["script_id"])
        return JSONResponse(draft.model_dump(mode="json"))

    async def save_draft(request: Request) -> JSONResponse:
        body = await _json_body(request)
        draft = repository.save_draft(
            request.path_params["script_id"],
            expected_revision=_required_int(body, "revision"),
            script=ProgramScript.model_validate(body.get("script")),
        )
        return JSONResponse(draft.model_dump(mode="json"))

    async def validate_draft(request: Request) -> JSONResponse:
        issues = repository.validate_draft(request.path_params["script_id"])
        return JSONResponse(
            {"valid": not issues, "issues": [issue.model_dump(mode="json") for issue in issues]}
        )

    async def publish_draft(request: Request) -> JSONResponse:
        body = await _json_body(request)
        published = repository.publish(
            request.path_params["script_id"],
            expected_revision=_required_int(body, "revision"),
        )
        return JSONResponse(published.model_dump(mode="json"), status_code=201)

    async def get_version(request: Request) -> JSONResponse:
        published = repository.get_published(
            request.path_params["script_id"],
            int(request.path_params["version"]),
        )
        return JSONResponse(published.model_dump(mode="json"))

    async def duplicate_version(request: Request) -> JSONResponse:
        body = await _json_body(request)
        draft = repository.duplicate_version(
            request.path_params["script_id"],
            int(request.path_params["version"]),
            new_id=_optional_string(body, "new_id"),
            title=_optional_string(body, "title"),
        )
        return JSONResponse(draft.model_dump(mode="json"), status_code=201)

    async def archive_script(request: Request) -> JSONResponse:
        repository.archive(request.path_params["script_id"])
        return JSONResponse({"ok": True})

    inbox = command_inbox or CommandInbox(":memory:")
    run_tasks: dict[str, CommandKey] = {}
    replay_tasks: dict[str, CommandKey] = {}
    command_waiters: dict[CommandKey, asyncio.Event] = {}

    async def start_once(
        key: CommandKey,
        command: dict[str, Any],
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        waiter = command_waiters.get(key)
        created_waiter = waiter is None
        if waiter is None:
            waiter = command_waiters.setdefault(key, asyncio.Event())
        decision = await inbox.accept(key, command)
        try:
            existing = await _existing_http_result(
                inbox,
                decision,
                None
                if created_waiter and decision.decision is CommandDecision.OBSERVE
                else command_waiters,
            )
        except Exception:
            if created_waiter:
                command_waiters.pop(key, None)
            raise
        if existing is not None:
            if created_waiter:
                command_waiters.pop(key, None)
            return existing
        await inbox.mark_processing(key)
        try:
            result = await operation()
            await _sync_long_task(inbox, key, result)
            return result
        except Exception as exc:
            await inbox.fail(key, error_code=_error_code(exc), error_message=str(exc))
            raise
        finally:
            waiter.set()
            command_waiters.pop(key, None)

    async def start_run(request: Request) -> JSONResponse:
        body = await _json_body(request)
        task_id = _optional_string(body, "task_id") or str(uuid4())
        creator_id = _creator_id(body)
        command = {
            "script_id": _required_string(body, "script_id"),
            "version": _required_int(body, "version"),
            "room_id": _required_int(body, "room_id"),
            "creator_id": creator_id,
        }
        key = CommandKey("dashboard", "program.start", task_id)
        snapshot = await start_once(key, command, lambda: runner.start(**command))
        if "run_id" in snapshot:
            run_tasks[str(snapshot["run_id"])] = key
        return JSONResponse(snapshot, status_code=202)

    async def get_current_run(request: Request) -> JSONResponse:
        room_id = int(request.query_params.get("room_id", "1"))
        return JSONResponse({"run": runner.get_current(room_id)})

    async def get_run(request: Request) -> JSONResponse:
        snapshot = runner.get_run(request.path_params["run_id"])
        await _sync_long_task(inbox, run_tasks.get(request.path_params["run_id"]), snapshot)
        return JSONResponse(snapshot)

    async def submit_choice(request: Request) -> JSONResponse:
        body = await _json_body(request)
        command_id = _optional_string(body, "command_id") or str(uuid4())
        command = {
            "run_id": request.path_params["run_id"],
            "beat_id": _required_string(body, "beat_id"),
            "option_id": _required_string(body, "option_id"),
            "creator_id": _creator_id(body),
        }
        snapshot = await _run_immediate_command(
            inbox,
            CommandKey("dashboard", "program.choice", command_id),
            command,
            lambda: runner.submit_choice(**command),
            command_waiters,
        )
        await _sync_long_task(inbox, run_tasks.get(request.path_params["run_id"]), snapshot)
        return JSONResponse(snapshot, status_code=202)

    async def control_run(request: Request) -> JSONResponse:
        body = await _json_body(request)
        command_id = _optional_string(body, "command_id") or str(uuid4())
        command = {
            "run_id": request.path_params["run_id"],
            "action": _required_string(body, "action"),
            "creator_id": _creator_id(body),
        }
        snapshot = await _run_immediate_command(
            inbox,
            CommandKey("dashboard", "program.control", command_id),
            command,
            lambda: runner.control(**command),
            command_waiters,
        )
        await _sync_long_task(inbox, run_tasks.get(request.path_params["run_id"]), snapshot)
        return JSONResponse(snapshot)

    async def start_replay(request: Request) -> JSONResponse:
        body = await _json_body(request)
        source = _required_string(body, "source")
        if source == "script":
            published = repository.get_published(
                _required_string(body, "script_id"),
                _required_int(body, "version"),
            )
            raw_selections = body.get("selections", {})
            if not isinstance(raw_selections, dict):
                raise ValueError("selections must be an object")
            events = compile_script_events(
                published.script,
                {str(key): str(value) for key, value in raw_selections.items()},
            )
        elif source == "jsonl":
            events = parse_jsonl_events(_required_string(body, "jsonl"))
        else:
            raise ValueError("source must be script or jsonl")
        task_id = _optional_string(body, "task_id") or str(uuid4())
        command = {
            "source": source,
            "events": [_replay_event_payload(event) for event in events],
            "room_id": _required_int(body, "room_id"),
            "creator_id": _creator_id(body),
            "speed": float(body.get("speed", 1)),
        }
        key = CommandKey("dashboard", "replay.start", task_id)
        snapshot = await start_once(
            key,
            command,
            lambda: replay.start(
                events,
                room_id=command["room_id"],
                creator_id=command["creator_id"],
                source=source,
                speed=command["speed"],
            ),
        )
        if "replay_id" in snapshot:
            replay_tasks[str(snapshot["replay_id"])] = key
        return JSONResponse(snapshot, status_code=202)

    async def get_replay(request: Request) -> JSONResponse:
        snapshot = replay.get_run(request.path_params["replay_id"])
        await _sync_long_task(inbox, replay_tasks.get(request.path_params["replay_id"]), snapshot)
        return JSONResponse(snapshot)

    async def control_replay(request: Request) -> JSONResponse:
        body = await _json_body(request)
        speed_value = body.get("speed")
        command_id = _optional_string(body, "command_id") or str(uuid4())
        command = {
            "replay_id": request.path_params["replay_id"],
            "action": _required_string(body, "action"),
            "creator_id": _creator_id(body),
            "speed": float(speed_value) if speed_value is not None else None,
        }
        snapshot = await _run_immediate_command(
            inbox,
            CommandKey("dashboard", "replay.control", command_id),
            command,
            lambda: replay.control(**command),
            command_waiters,
        )
        await _sync_long_task(inbox, replay_tasks.get(request.path_params["replay_id"]), snapshot)
        return JSONResponse(snapshot)

    routes = [
        Route("/api/program-scripts", list_scripts),
        Route("/api/program-scripts/drafts", create_draft, methods=["POST"]),
        Route("/api/program-scripts/drafts/{script_id:str}", get_draft, methods=["GET"]),
        Route("/api/program-scripts/drafts/{script_id:str}", save_draft, methods=["PUT"]),
        Route(
            "/api/program-scripts/drafts/{script_id:str}/validate",
            validate_draft,
            methods=["POST"],
        ),
        Route(
            "/api/program-scripts/drafts/{script_id:str}/publish",
            publish_draft,
            methods=["POST"],
        ),
        Route(
            "/api/program-scripts/{script_id:str}/versions/{version:int}",
            get_version,
        ),
        Route(
            "/api/program-scripts/{script_id:str}/versions/{version:int}/duplicate",
            duplicate_version,
            methods=["POST"],
        ),
        Route(
            "/api/program-scripts/{script_id:str}/archive",
            archive_script,
            methods=["POST"],
        ),
        Route("/api/program-runs/start", start_run, methods=["POST"]),
        Route("/api/program-runs/current", get_current_run),
        Route("/api/program-runs/{run_id:str}", get_run),
        Route("/api/program-runs/{run_id:str}/choice", submit_choice, methods=["POST"]),
        Route("/api/program-runs/{run_id:str}/control", control_run, methods=["POST"]),
        Route("/api/program-replays/start", start_replay, methods=["POST"]),
        Route("/api/program-replays/{replay_id:str}", get_replay),
        Route(
            "/api/program-replays/{replay_id:str}/control",
            control_replay,
            methods=["POST"],
        ),
    ]
    return [_ErrorRoute(route) for route in routes]


async def _existing_http_result(
    inbox: CommandInbox,
    decision: Any,
    waiters: dict[CommandKey, asyncio.Event] | None = None,
) -> dict[str, Any] | None:
    if decision.decision is CommandDecision.CONFLICT:
        raise ValueError("IDEMPOTENCY_CONFLICT")
    if decision.decision is CommandDecision.REPLAY and decision.task:
        return dict(decision.task.result or {})
    if decision.decision is CommandDecision.OBSERVE and decision.task:
        waiter = waiters.get(decision.task.key) if waiters else None
        if waiter is not None:
            await waiter.wait()
            return _existing_task_result((await inbox.get(decision.task.key)).task)
        return dict(decision.task.progress or decision.task.snapshot(reused=True))
    if decision.decision is CommandDecision.TERMINAL and decision.task:
        raise ValueError(decision.task.error_code or decision.task.status.value)
    return None


def _existing_task_result(task: Any) -> dict[str, Any]:
    if task is None:
        raise ValueError("TASK_NOT_FOUND")
    if task.status.value == "succeeded":
        return dict(task.result or {})
    if task.status.value in {"failed", "cancelled", "interrupted"}:
        raise ValueError(task.error_code or task.status.value)
    return dict(task.progress or task.snapshot(reused=True))


async def _run_immediate_command(
    inbox: CommandInbox,
    key: CommandKey,
    request: dict[str, Any],
    operation: Callable[[], Awaitable[dict[str, Any]]],
    waiters: dict[CommandKey, asyncio.Event] | None = None,
) -> dict[str, Any]:
    waiter = waiters.get(key) if waiters is not None else None
    created_waiter = waiter is None and waiters is not None
    if created_waiter and waiters is not None:
        waiter = waiters.setdefault(key, asyncio.Event())
    decision = await inbox.accept(key, request)
    try:
        existing = await _existing_http_result(
            inbox,
            decision,
            None if created_waiter and decision.decision is CommandDecision.OBSERVE else waiters,
        )
    except Exception:
        if created_waiter and waiters is not None:
            waiters.pop(key, None)
        raise
    if existing is not None:
        if created_waiter and waiters is not None:
            waiters.pop(key, None)
        return existing
    await inbox.mark_processing(key)
    try:
        result = await operation()
    except Exception as exc:
        await inbox.fail(key, error_code=_error_code(exc), error_message=str(exc))
        raise
    else:
        await inbox.succeed(key, result)
        return result
    finally:
        if waiter is not None:
            waiter.set()
            waiters.pop(key, None)


async def _sync_long_task(
    inbox: CommandInbox,
    key: CommandKey | None,
    snapshot: dict[str, Any],
) -> None:
    if key is None:
        return
    state = str(snapshot.get("state") or "")
    if state in {"completed", "stopped"}:
        await inbox.succeed(key, snapshot)
    elif state == "failed":
        await inbox.fail(
            key,
            error_code=str(snapshot.get("error") or "RUN_FAILED"),
            error_message=str(snapshot.get("error") or "Run failed"),
        )
    else:
        await inbox.update_progress(key, snapshot)


def _error_code(exc: Exception) -> str:
    return str(getattr(exc, "code", type(exc).__name__)).upper()


def _replay_event_payload(event: Any) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "offset_ms": event.offset_ms,
        "event_type": event.event_type.value,
        "actor_id": event.actor_id,
        "text": event.text,
        "payload": event.payload,
    }


class _ErrorRoute(BaseRoute):
    """Keep domain/API error rendering out of each small endpoint closure."""

    def __init__(self, route: Route) -> None:
        self.route = route

    def matches(
        self,
        scope: MutableMapping[str, Any],
    ) -> tuple[Match, MutableMapping[str, Any]]:
        return self.route.matches(scope)

    def url_path_for(self, name: str, /, **path_params: Any) -> Any:
        return self.route.url_path_for(name, **path_params)

    async def handle(
        self,
        scope: MutableMapping[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        try:
            await self.route.handle(scope, receive, send)
        except (ProgramScriptRepositoryError, ProgramRuntimeError, ReplayCoordinatorError) as exc:
            await JSONResponse(
                {"error_code": exc.code, "message": str(exc)},
                status_code=exc.status_code,
            )(scope, receive, send)
        except ValidationError as exc:
            await JSONResponse(
                {
                    "error_code": "validation_error",
                    "message": "配置格式无效",
                    "issues": exc.errors(),
                },
                status_code=422,
            )(scope, receive, send)
        except (TypeError, ValueError) as exc:
            await JSONResponse(
                {"error_code": "invalid_request", "message": str(exc)}, status_code=400
            )(scope, receive, send)


async def _json_body(request: Request) -> dict[str, Any]:
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("request body must be an object")
    return body


def _required_string(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _optional_string(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _required_int(body: dict[str, Any], key: str) -> int:
    value = body.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _creator_id(body: dict[str, Any]) -> str:
    return _optional_string(body, "creator_id") or "dashboard"
