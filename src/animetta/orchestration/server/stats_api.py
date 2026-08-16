"""Pipeline stats HTTP API"""

from typing import Any

from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route

from animetta.core.service_pool import ServicePool
from animetta.observability.dto import (
    HealthDTO,
    OperationAggregateDTO,
    OverviewDTO,
    TraceDetailDTO,
    TraceSummaryDTO,
    versioned_events,
)
from animetta.observability.live_dashboard import live_overview, live_turn_detail
from animetta.observability.ports import ObservationQuery

# ── Module-level references for health check enrichment ──────
_model_manager: Any | None = None
_runtime_config: Any | None = None
_component_readiness_cache: Any | None = None
_checkpoint_readiness: dict[str, object | None] = {
    "state": "degraded",
    "ready": False,
    "degraded": True,
    "reason": "not_started",
}
_auth_session_readiness: dict[str, object | None] = {
    "state": "failed",
    "ready": False,
    "reason": "not_started",
}
_frontend_readiness: dict[str, str | bool | None] = {
    "state": "failed",
    "ready": False,
    "reason": "frontend_state_unavailable",
}


def set_model_manager(manager: Any) -> None:
    """Register the ModelLoadingManager so /health can report model states."""
    global _model_manager
    _model_manager = manager


def set_runtime_readiness_context(
    config: Any,
    frontend: dict[str, str | bool | None],
) -> None:
    """Cache lightweight runtime inputs consumed by the /ready endpoint."""
    global _runtime_config, _frontend_readiness
    _runtime_config = config
    _frontend_readiness = dict(frontend)


def set_component_readiness_cache(cache: Any | None) -> None:
    """Register the background-owned local component readiness cache."""
    global _component_readiness_cache
    _component_readiness_cache = cache


def set_checkpoint_readiness(value: dict[str, object | None]) -> None:
    """Cache the content-free durable execution status."""
    global _checkpoint_readiness
    _checkpoint_readiness = dict(value)


def set_auth_session_readiness(value: dict[str, object | None]) -> None:
    """Cache the dedicated browser-session store status."""
    global _auth_session_readiness
    _auth_session_readiness = dict(value)


async def stats_overview(request: Request) -> JSONResponse:
    """GET /api/stats/overview"""
    try:
        data = await _get_observation_query(request).overview()
        return JSONResponse(OverviewDTO.model_validate(data).public_dict())
    except Exception as e:
        logger.error(f"[StatsAPI] overview failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_nodes(request: Request) -> JSONResponse:
    """GET /api/stats/nodes"""
    try:
        data = await _get_observation_query(request).operation_aggregates()
        return JSONResponse(
            [OperationAggregateDTO.model_validate(item).public_dict() for item in data]
        )
    except Exception as e:
        logger.error(f"[StatsAPI] nodes failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_traces(request: Request) -> JSONResponse:
    """GET /api/stats/traces?limit=50&offset=0"""
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
        data = await _get_observation_query(request).recent_traces(limit, offset)
        return JSONResponse([TraceSummaryDTO.model_validate(item).public_dict() for item in data])
    except Exception as e:
        logger.error(f"[StatsAPI] traces failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_trace_detail(request: Request) -> JSONResponse:
    """GET /api/stats/traces/{trace_id}"""
    try:
        trace_id = request.path_params["trace_id"]
        data = await _get_observation_query(request).trace_detail(trace_id)
        if not data:
            return JSONResponse({"error": "Trace not found"}, status_code=404)
        return JSONResponse(TraceDetailDTO.from_ledger(dict(data)).public_dict())
    except Exception as e:
        logger.error(f"[StatsAPI] trace_detail failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_trace_tree(request: Request) -> JSONResponse:
    """GET /api/stats/traces/{trace_id}/tree — canonical operation hierarchy."""
    try:
        trace_id = request.path_params["trace_id"]
        detail = await _get_observation_query(request).trace_detail(trace_id)
        if not detail:
            return JSONResponse({"error": "Trace not found"}, status_code=404)

        return JSONResponse(TraceDetailDTO.from_ledger(dict(detail)).public_dict())
    except Exception as e:
        logger.error(f"[StatsAPI] trace_tree failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_trace_events(request: Request) -> JSONResponse:
    """GET /api/stats/traces/{trace_id}/events."""
    try:
        trace_id = request.path_params["trace_id"]
        events = await _get_observation_query(request).trace_events(trace_id)
        return JSONResponse(versioned_events([dict(event) for event in events]))
    except Exception as e:
        logger.error(f"[StatsAPI] trace_events failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_live(request: Request) -> JSONResponse:
    """GET /api/stats/live?limit=20 — live-console turns and headline metrics."""
    try:
        limit = int(request.query_params.get("limit", "20"))
        data = await live_overview(_get_observation_query(request), limit=limit)
        return JSONResponse(data)
    except Exception as exc:
        logger.error(f"[StatsAPI] live failed: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


async def stats_live_turn(request: Request) -> JSONResponse:
    """GET /api/stats/live/turns/{trace_id} — deterministic public execution timeline."""
    try:
        data = await live_turn_detail(
            _get_observation_query(request),
            trace_id=request.path_params["trace_id"],
        )
        if data is None:
            return JSONResponse({"error": "Turn not found"}, status_code=404)
        return JSONResponse(data)
    except Exception as exc:
        logger.error(f"[StatsAPI] live_turn failed: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


async def stats_observation_health(request: Request) -> JSONResponse:
    """GET /api/stats/observation-health."""
    try:
        health = await _get_observation_query(request).observation_health()
        return JSONResponse(HealthDTO.from_health(health).public_dict())
    except Exception as e:
        logger.error(f"[StatsAPI] observation_health failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def health_check(request: Request) -> JSONResponse:
    """Cheap process liveness check; never waits for providers or models."""
    import time

    del request

    return JSONResponse(
        {
            "status": "ok",
            "service": "anima",
            "timestamp": time.time(),
        },
        status_code=200,
    )


async def readiness_check(request: Request) -> JSONResponse:
    """Return the cached runtime snapshot without performing network/model I/O."""
    try:
        snapshot = ServicePool.get_readiness_snapshot(
            config=_runtime_config,
            model_manager=_model_manager,
            frontend=_frontend_readiness,
        )
        payload = snapshot.to_dict()
        _merge_component_readiness(payload)
        return JSONResponse(payload, status_code=200 if payload["ready"] else 503)
    except Exception as exc:
        logger.warning(
            "[ready] Snapshot unavailable: {}",
            type(exc).__name__,
        )
        return JSONResponse(
            {
                "status": "not_ready",
                "ready": False,
                "service": "anima",
                "reason": "snapshot_unavailable",
            },
            status_code=503,
        )


def _merge_component_readiness(payload: dict[str, Any]) -> None:
    """Merge cached local checks into canonical-profile readiness without I/O."""
    if payload.get("profile") not in {"test", "smoke", "selftest", "production"}:
        return
    required = {"memory_runtime"}
    observation = getattr(_runtime_config, "observability", None)
    if getattr(observation, "enabled", False):
        required.add("observation_ledger")
        if getattr(getattr(observation, "prometheus", None), "enabled", False):
            required.add("metrics_projection")
    providers = getattr(_runtime_config, "providers", None)
    configured_tts = providers.get("tts") if hasattr(providers, "get") else None
    if getattr(configured_tts, "type", None) == "remote":
        required.add("remote_tts")

    if _component_readiness_cache is None:
        local_snapshot = {
            "age_seconds": None,
            "components": {
                name: {
                    "state": "failed",
                    "ready": False,
                    "reason": "cache_unavailable",
                }
                for name in required
            },
        }
    else:
        local_snapshot = _component_readiness_cache.snapshot()

    components = payload.setdefault("components", {})
    components["checkpoint"] = {**_checkpoint_readiness, "required": False}
    components["auth_session"] = {**_auth_session_readiness, "required": True}
    payload["degraded"] = _checkpoint_readiness.get("degraded") is True
    local_components = local_snapshot.get("components", {})
    local_ready = True
    for name in required:
        component = dict(
            local_components.get(
                name,
                {"state": "failed", "ready": False, "reason": "cache_unavailable"},
            )
        )
        component["required"] = True
        components[name] = component
        local_ready = local_ready and component.get("ready") is True
    payload["component_status_age_seconds"] = local_snapshot.get("age_seconds")
    payload["ready"] = bool(
        payload.get("ready") and local_ready and _auth_session_readiness.get("ready") is True
    )
    payload["status"] = "ready" if payload["ready"] else "not_ready"


def _get_gpu_info() -> dict[str, Any]:
    """Return GPU availability, device name, and memory stats.

    Returns a dict with keys:
        available (bool), name (str|None), memory_total_mb (float|None),
        memory_used_mb (float|None), memory_free_mb (float|None).
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return {"available": False}

        device_name = torch.cuda.get_device_name(0)
        properties = torch.cuda.get_device_properties(0)
        total_bytes = getattr(properties, "total_memory", None)
        if total_bytes is None:
            total_bytes = getattr(properties, "total_mem")
        total = total_bytes / (1024 * 1024)
        reserved = torch.cuda.memory_reserved(0) / (1024 * 1024)
        allocated = torch.cuda.memory_allocated(0) / (1024 * 1024)
        free = total - reserved

        return {
            "available": True,
            "name": device_name,
            "memory_total_mb": round(total, 1),
            "memory_used_mb": round(allocated, 1),
            "memory_free_mb": round(free, 1),
        }
    except ImportError:
        return {"available": False, "name": None}
    except Exception as e:
        logger.warning(f"[health/gpu] GPU info probe failed: {e}")
        return {"available": False, "error": str(e)}


async def stats_inspection_latest(request: Request) -> JSONResponse:
    """GET /api/stats/inspection/latest — most recent inspection report."""
    try:
        reports = await _get_observation_query(request).inspection_reports(1, 0)
        data = reports[0] if reports else None
        if data is None:
            return JSONResponse({"error": "No inspection reports yet"}, status_code=404)
        return JSONResponse({"api_version": "2", **dict(data)})
    except Exception as e:
        logger.error(f"[StatsAPI] inspection_latest failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def get_stats_routes() -> list[BaseRoute]:
    """Return the route list for the stats API"""
    return [
        Route("/health", health_check),
        Route("/ready", readiness_check),
        Route("/api/stats/overview", stats_overview),
        Route("/api/stats/nodes", stats_nodes),
        Route("/api/stats/traces", stats_traces),
        Route("/api/stats/traces/{trace_id}", stats_trace_detail),
        Route("/api/stats/traces/{trace_id}/tree", stats_trace_tree),
        Route("/api/stats/traces/{trace_id}/events", stats_trace_events),
        Route("/api/stats/live", stats_live),
        Route("/api/stats/live/turns/{trace_id}", stats_live_turn),
        Route("/api/stats/observation-health", stats_observation_health),
        Route("/api/stats/inspection/latest", stats_inspection_latest),
    ]


def _get_observation_query(request: Request) -> ObservationQuery:
    query = getattr(request.app.state, "observation_query", None)
    if query is None:
        raise RuntimeError("ObservationQuery is not configured")
    return query
