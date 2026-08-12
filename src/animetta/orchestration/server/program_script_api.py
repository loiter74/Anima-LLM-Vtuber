"""Starlette control plane for program scripts, runs, and danmaku replay."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Match, Route

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

    async def start_run(request: Request) -> JSONResponse:
        body = await _json_body(request)
        snapshot = await runner.start(
            _required_string(body, "script_id"),
            _required_int(body, "version"),
            room_id=_required_int(body, "room_id"),
            creator_id=_creator_id(body),
        )
        return JSONResponse(snapshot, status_code=202)

    async def get_current_run(request: Request) -> JSONResponse:
        room_id = int(request.query_params.get("room_id", "1"))
        return JSONResponse({"run": runner.get_current(room_id)})

    async def get_run(request: Request) -> JSONResponse:
        return JSONResponse(runner.get_run(request.path_params["run_id"]))

    async def submit_choice(request: Request) -> JSONResponse:
        body = await _json_body(request)
        snapshot = await runner.submit_choice(
            request.path_params["run_id"],
            _required_string(body, "beat_id"),
            _required_string(body, "option_id"),
            creator_id=_creator_id(body),
        )
        return JSONResponse(snapshot, status_code=202)

    async def control_run(request: Request) -> JSONResponse:
        body = await _json_body(request)
        snapshot = await runner.control(
            request.path_params["run_id"],
            _required_string(body, "action"),
            creator_id=_creator_id(body),
        )
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
        snapshot = await replay.start(
            events,
            room_id=_required_int(body, "room_id"),
            creator_id=_creator_id(body),
            source=source,
            speed=float(body.get("speed", 1)),
        )
        return JSONResponse(snapshot, status_code=202)

    async def get_replay(request: Request) -> JSONResponse:
        return JSONResponse(replay.get_run(request.path_params["replay_id"]))

    async def control_replay(request: Request) -> JSONResponse:
        body = await _json_body(request)
        speed_value = body.get("speed")
        snapshot = await replay.control(
            request.path_params["replay_id"],
            _required_string(body, "action"),
            creator_id=_creator_id(body),
            speed=float(speed_value) if speed_value is not None else None,
        )
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
