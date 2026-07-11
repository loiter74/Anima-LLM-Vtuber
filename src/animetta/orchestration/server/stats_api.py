"""Pipeline stats HTTP API"""

from pathlib import Path
from typing import Any

from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from animetta.core.service_pool import ServicePool

from ..graph.stats_store import get_stats_store

# ── Module-level references for health check enrichment ──────
_model_manager: Any | None = None
_runtime_config: Any | None = None
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

# Dashboard frontend file directory
STATS_FRONTEND_DIR = str(
    Path(__file__).parent.parent.parent.parent.parent / "frontend" / "stats"
)


async def stats_overview(request: Request) -> JSONResponse:
    """GET /api/stats/overview"""
    try:
        store = await get_stats_store()
        data = await store.get_overview()
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[StatsAPI] overview failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_nodes(request: Request) -> JSONResponse:
    """GET /api/stats/nodes"""
    try:
        store = await get_stats_store()
        data = await store.get_node_stats()
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[StatsAPI] nodes failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_traces(request: Request) -> JSONResponse:
    """GET /api/stats/traces?limit=50&offset=0"""
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
        store = await get_stats_store()
        data = await store.get_recent_traces(limit, offset)
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[StatsAPI] traces failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_trace_detail(request: Request) -> JSONResponse:
    """GET /api/stats/traces/{trace_id}"""
    try:
        trace_id = request.path_params["trace_id"]
        store = await get_stats_store()
        data = await store.get_trace_detail(trace_id)
        if not data:
            return JSONResponse({"error": "Trace not found"}, status_code=404)
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[StatsAPI] trace_detail failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_trace_tree(request: Request) -> JSONResponse:
    """GET /api/stats/traces/{trace_id}/tree — returns spans as a nested tree."""
    try:
        trace_id = request.path_params["trace_id"]
        store = await get_stats_store()
        detail = await store.get_trace_detail(trace_id)
        if not detail:
            return JSONResponse({"error": "Trace not found"}, status_code=404)

        spans: list[dict[str, Any]] = detail.get("spans", [])
        tree = _build_span_tree(spans)
        return JSONResponse({
            **detail,
            "spans": spans,
            "tree": tree,
        })
    except Exception as e:
        logger.error(f"[StatsAPI] trace_tree failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def _build_span_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group flat span list into a parent-child nested tree.

    Returns a list of root spans (parent_span_id is None), each with a ``children`` list.
    """
    by_id: dict[str, dict] = {}
    roots: list[dict] = []

    for s in spans:
        node = dict(s)
        node["children"] = []
        by_id[s["span_id"]] = node

    for node in by_id.values():
        pid = node.get("parent_span_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(node)
        else:
            roots.append(node)

    return roots


async def health_check(request):
    """Cheap process liveness check; never waits for providers or models."""
    import time

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


def _get_model_status() -> dict[str, str]:
    """Return per-model loading states from ModelLoadingManager.

    Returns a dict mapping model name → state string
    (unloaded / loading / loaded / error).
    """
    if _model_manager is None:
        return {}
    try:
        return _model_manager.get_status()
    except Exception as e:
        logger.warning(f"[health/models] Failed to get model status: {e}")
        return {"_error": str(e)}


async def stats_inspection_latest(request: Request) -> JSONResponse:
    """GET /api/stats/inspection/latest — most recent inspection report."""
    try:
        store = await get_stats_store()
        data = await store.get_latest_inspection_report()
        if data is None:
            return JSONResponse(
                {"error": "No inspection reports yet"}, status_code=404
            )
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[StatsAPI] inspection_latest failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def get_stats_routes():
    """Return the route list for the stats API"""
    return [
        Route("/health", health_check),
        Route("/ready", readiness_check),
        Route("/api/stats/overview", stats_overview),
        Route("/api/stats/nodes", stats_nodes),
        Route("/api/stats/traces", stats_traces),
        Route("/api/stats/traces/{trace_id}", stats_trace_detail),
        Route("/api/stats/traces/{trace_id}/tree", stats_trace_tree),
        Route("/api/stats/inspection/latest", stats_inspection_latest),
        Mount("/stats", app=StaticFiles(directory=STATS_FRONTEND_DIR, html=True), name="stats_dashboard"),
    ]
