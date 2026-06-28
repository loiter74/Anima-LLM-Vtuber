# Pipeline Stats Dashboard 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 Anima 的 LangGraph 调用链路建立全链路可观测性统计面板，采集各节点耗时、调用统计和链路溯源数据。

**Architecture:** 通过自定义 LangChain `BaseCallbackHandler` 采集节点生命周期事件，存入 SQLite，通过 Starlette HTTP API 暴露数据，前端用 vanilla JS + Chart.js 展示。零侵入 —— 不修改任何现有节点代码。

**Tech Stack:** LangChain CallbackHandler, SQLite (aiosqlite), Starlette HTTP routes, Chart.js, vanilla JS/HTML/CSS

---

### Task 1: SQLite 存储层 —— StatsStore

**Files:**
- Create: `src/animetta/orchestration/graph/stats_store.py`

**Step 1: 创建 StatsStore 类**

```python
"""Pipeline 统计数据存储"""

import aiosqlite
import uuid
import time
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
from loguru import logger


class StatsStore:
    """SQLite 统计存储"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent.parent.parent.parent / "data" / "stats.db")
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self):
        """初始化数据库连接和表结构"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._create_tables()

    async def _create_tables(self):
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                session_id TEXT,
                input_type TEXT,
                user_text TEXT,
                total_duration_ms REAL,
                status TEXT DEFAULT 'running',
                error_msg TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS spans (
                span_id TEXT PRIMARY KEY,
                trace_id TEXT REFERENCES traces(trace_id),
                parent_span_id TEXT,
                node_name TEXT,
                duration_ms REAL,
                status TEXT DEFAULT 'running',
                input_summary TEXT,
                output_summary TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_traces_created ON traces(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
            CREATE INDEX IF NOT EXISTS idx_spans_node ON spans(node_name);
        """)
        await self._db.commit()

    async def create_trace(self, trace_id: str, session_id: str,
                           input_type: str, user_text: str) -> None:
        truncated = user_text[:100] if user_text else ""
        await self._db.execute(
            "INSERT INTO traces (trace_id, session_id, input_type, user_text) VALUES (?, ?, ?, ?)",
            (trace_id, session_id, input_type, truncated)
        )
        await self._db.commit()

    async def finish_trace(self, trace_id: str, total_duration_ms: float,
                           status: str = "success", error_msg: str = None) -> None:
        await self._db.execute(
            "UPDATE traces SET total_duration_ms=?, status=?, error_msg=? WHERE trace_id=?",
            (total_duration_ms, status, error_msg, trace_id)
        )
        await self._db.commit()

    async def create_span(self, span_id: str, trace_id: str, node_name: str,
                          parent_span_id: str = None,
                          input_summary: str = None) -> None:
        await self._db.execute(
            "INSERT INTO spans (span_id, trace_id, parent_span_id, node_name, input_summary) VALUES (?, ?, ?, ?, ?)",
            (span_id, trace_id, parent_span_id, node_name, input_summary)
        )
        await self._db.commit()

    async def finish_span(self, span_id: str, duration_ms: float,
                          status: str = "success", output_summary: str = None) -> None:
        await self._db.execute(
            "UPDATE spans SET duration_ms=?, status=?, output_summary=? WHERE span_id=?",
            (duration_ms, status, output_summary, span_id)
        )
        await self._db.commit()

    async def get_overview(self) -> Dict[str, Any]:
        cursor = await self._db.execute("""
            SELECT
                COUNT(*) as total_requests,
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success_count,
                AVG(total_duration_ms) as avg_duration
            FROM traces
        """)
        row = await cursor.fetchone()

        total = row[0] or 0
        success = row[1] or 0

        # P95
        p95_cursor = await self._db.execute("""
            SELECT total_duration_ms FROM traces
            WHERE status='success' AND total_duration_ms IS NOT NULL
            ORDER BY total_duration_ms DESC
            LIMIT 1 OFFSET (SELECT COUNT(*) * 5 / 100 FROM traces WHERE status='success' AND total_duration_ms IS NOT NULL)
        """)
        p95_row = await p95_cursor.fetchone()

        return {
            "total_requests": total,
            "success_rate": round(success / total * 100, 1) if total > 0 else 0,
            "avg_duration_ms": round(row[2], 1) if row[2] else 0,
            "p95_duration_ms": round(p95_row[0], 1) if p95_row else 0,
        }

    async def get_node_stats(self) -> List[Dict[str, Any]]:
        cursor = await self._db.execute("""
            SELECT
                node_name,
                COUNT(*) as call_count,
                AVG(duration_ms) as avg_duration_ms,
                MIN(duration_ms) as min_duration_ms,
                MAX(duration_ms) as max_duration_ms,
                SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_count
            FROM spans
            WHERE duration_ms IS NOT NULL
            GROUP BY node_name
            ORDER BY avg_duration_ms DESC
        """)
        rows = await cursor.fetchall()
        return [
            {
                "node_name": row[0],
                "call_count": row[1],
                "avg_duration_ms": round(row[2], 1),
                "min_duration_ms": round(row[3], 1),
                "max_duration_ms": round(row[4], 1),
                "error_count": row[5],
                "error_rate": round(row[5] / row[1] * 100, 1) if row[1] > 0 else 0,
            }
            for row in rows
        ]

    async def get_recent_traces(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT trace_id, session_id, input_type, user_text, total_duration_ms, status, created_at FROM traces ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        rows = await cursor.fetchall()
        return [
            {
                "trace_id": row[0],
                "session_id": row[1],
                "input_type": row[2],
                "user_text": row[3],
                "total_duration_ms": row[4],
                "status": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]

    async def get_trace_detail(self, trace_id: str) -> Optional[Dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT trace_id, session_id, input_type, user_text, total_duration_ms, status, error_msg, created_at FROM traces WHERE trace_id=?",
            (trace_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None

        span_cursor = await self._db.execute(
            "SELECT span_id, parent_span_id, node_name, duration_ms, status, input_summary, output_summary, created_at FROM spans WHERE trace_id=? ORDER BY created_at",
            (trace_id,)
        )
        spans = [
            {
                "span_id": s[0],
                "parent_span_id": s[1],
                "node_name": s[2],
                "duration_ms": s[3],
                "status": s[4],
                "input_summary": s[5],
                "output_summary": s[6],
                "created_at": s[7],
            }
            for s in await span_cursor.fetchall()
        ]

        return {
            "trace_id": row[0],
            "session_id": row[1],
            "input_type": row[2],
            "user_text": row[3],
            "total_duration_ms": row[4],
            "status": row[5],
            "error_msg": row[6],
            "created_at": row[7],
            "spans": spans,
        }

    async def close(self):
        if self._db:
            await self._db.close()


# 全局单例
_store: Optional[StatsStore] = None


async def get_stats_store() -> StatsStore:
    global _store
    if _store is None:
        _store = StatsStore()
        await _store.init()
    return _store
```

**Step 2: 验证导入**

Run: `cd /c/Users/30262/Project/Anima && python -c "from anima.orchestration.graph.stats_store import StatsStore; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/animetta/orchestration/graph/stats_store.py
git commit -m "feat: 添加 StatsStore SQLite 存储层"
```

---

### Task 2: Callback Handler —— StatsCallbackHandler

**Files:**
- Create: `src/animetta/orchestration/graph/stats_handler.py`

**Step 1: 创建 StatsCallbackHandler**

关键点：LangGraph 每个节点执行时会触发 `on_chain_start` / `on_chain_end`。通过 `serialized.get("name")` 或 `kwargs.get("name")` 获取节点名称。用 `run_id` 关联 span。

```python
"""Pipeline 统计 Callback Handler"""

import time
import uuid
import threading
from typing import Any, Dict, Optional
from loguru import logger

from langchain_core.callbacks import BaseCallbackHandler

from .stats_store import get_stats_store


class StatsCallbackHandler(BaseCallbackHandler):
    """采集 LangGraph 节点执行耗时"""

    def __init__(self):
        self._active_spans: Dict[str, dict] = {}  # run_id -> span info
        self._trace_id: Optional[str] = None
        self._trace_start: Optional[float] = None
        self._lock = threading.Lock()

    def start_trace(self, session_id: str, input_type: str, user_text: str) -> str:
        """开始一次 trace（在 orchestrator 层调用）"""
        import asyncio
        self._trace_id = str(uuid.uuid4())
        self._trace_start = time.perf_counter()
        self._active_spans.clear()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._async_create_trace(session_id, input_type, user_text))
            else:
                loop.run_until_complete(self._async_create_trace(session_id, input_type, user_text))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._async_create_trace(session_id, input_type, user_text))

        return self._trace_id

    async def _async_create_trace(self, session_id: str, input_type: str, user_text: str):
        try:
            store = await get_stats_store()
            await store.create_trace(self._trace_id, session_id, input_type, user_text)
        except Exception as e:
            logger.warning(f"[StatsHandler] 创建 trace 失败: {e}")

    def finish_trace(self, status: str = "success", error_msg: str = None):
        """结束一次 trace"""
        if not self._trace_id or not self._trace_start:
            return

        duration = (time.perf_counter() - self._trace_start) * 1000
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._async_finish_trace(duration, status, error_msg))
            else:
                loop.run_until_complete(self._async_finish_trace(duration, status, error_msg))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._async_finish_trace(duration, status, error_msg))

    async def _async_finish_trace(self, duration: float, status: str, error_msg: str):
        try:
            store = await get_stats_store()
            await store.finish_trace(self._trace_id, duration, status, error_msg)
        except Exception as e:
            logger.warning(f"[StatsHandler] 完成 trace 失败: {e}")

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], *,
                       run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        name = serialized.get("name") or kwargs.get("name") or ""
        # 过滤掉 LangGraph 内部节点，只记录业务节点
        known_nodes = {"asr_node", "llm_node", "tts_node", "emotion_node",
                       "output_node", "tool_node", "asr", "llm", "tts", "emotion",
                       "output", "tools", "_RouteInput", "_ShouldUseTools"}
        if name not in known_nodes:
            return

        with self._lock:
            span_id = str(uuid.uuid4())
            self._active_spans[str(run_id)] = {
                "span_id": span_id,
                "node_name": name,
                "start_time": time.perf_counter(),
                "trace_id": self._trace_id,
            }

            # 异步写入 span
            import asyncio
            input_summary = self._summarize_input(name, inputs)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(
                        self._async_create_span(span_id, self._trace_id, name, input_summary)
                    )
                else:
                    loop.run_until_complete(
                        self._async_create_span(span_id, self._trace_id, name, input_summary)
                    )
            except RuntimeError:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    self._async_create_span(span_id, self._trace_id, name, input_summary)
                )

    def on_chain_end(self, outputs: Dict[str, Any], *, run_id: Any, **kwargs: Any) -> None:
        run_key = str(run_id)
        with self._lock:
            span_info = self._active_spans.pop(run_key, None)
            if not span_info:
                return

        duration = (time.perf_counter() - span_info["start_time"]) * 1000
        output_summary = self._summarize_output(span_info["node_name"], outputs)

        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self._async_finish_span(span_info["span_id"], duration, output_summary)
                )
            else:
                loop.run_until_complete(
                    self._async_finish_span(span_info["span_id"], duration, output_summary)
                )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                self._async_finish_span(span_info["span_id"], duration, output_summary)
            )

    def on_chain_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        run_key = str(run_id)
        with self._lock:
            span_info = self._active_spans.pop(run_key, None)
            if not span_info:
                return

        duration = (time.perf_counter() - span_info["start_time"]) * 1000
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self._async_finish_span(span_info["span_id"], duration, str(error)[:200], status="error")
                )
            else:
                loop.run_until_complete(
                    self._async_finish_span(span_info["span_id"], duration, str(error)[:200], status="error")
                )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                self._async_finish_span(span_info["span_id"], duration, str(error)[:200], status="error")
            )

    async def _async_create_span(self, span_id: str, trace_id: str,
                                 node_name: str, input_summary: str):
        try:
            store = await get_stats_store()
            await store.create_span(span_id, trace_id, node_name, input_summary=input_summary)
        except Exception as e:
            logger.warning(f"[StatsHandler] 创建 span 失败: {e}")

    async def _async_finish_span(self, span_id: str, duration: float,
                                 output_summary: str, status: str = "success"):
        try:
            store = await get_stats_store()
            await store.finish_span(span_id, duration, status, output_summary)
        except Exception as e:
            logger.warning(f"[StatsHandler] 完成 span 失败: {e}")

    @staticmethod
    def _summarize_input(node_name: str, inputs: Dict) -> str:
        state = inputs.get("state") or inputs
        if isinstance(state, dict):
            text = state.get("user_text", "")
            if text:
                return text[:200]
        return ""

    @staticmethod
    def _summarize_output(node_name: str, outputs: Dict) -> str:
        if isinstance(outputs, dict):
            text = outputs.get("response_text", "")
            if text:
                return text[:200]
            text = outputs.get("user_text", "")
            if text:
                return text[:200]
        return ""
```

**Step 2: 验证导入**

Run: `cd /c/Users/30262/Project/Anima && python -c "from anima.orchestration.graph.stats_handler import StatsCallbackHandler; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/animetta/orchestration/graph/stats_handler.py
git commit -m "feat: 添加 StatsCallbackHandler 数据采集"
```

---

### Task 3: 集成到 Orchestrator

**Files:**
- Modify: `src/animetta/orchestration/graph/orchestrator.py`

**Step 1: 在 orchestrator.py 中注入 StatsCallbackHandler**

在文件顶部导入区域添加：

```python
from .stats_handler import StatsCallbackHandler
```

在 `__init__` 方法中，`self._callbacks` 赋值之后添加：

```python
        # 统计 handler
        self._stats_handler = StatsCallbackHandler()
        self._callbacks.append(self._stats_handler)
        logger.info(f"[{self.session_id}] [LangGraph] 统计 handler 已注入")
```

修改 `_run_graph` 方法，在 graph 调用前后包裹 trace 生命周期：

```python
    async def _run_graph(self, initial_state: AgentState) -> Dict[str, Any]:
        """运行状态图，通过 LangGraph config 传递服务上下文"""
        # 开始 trace
        input_type = initial_state.get("input_type", "text")
        user_text = initial_state.get("user_text", "")
        self._stats_handler.start_trace(self.session_id, input_type, user_text)

        run_config = dict(self._langgraph_config)
        callbacks = self._callbacks or get_observability().callbacks
        if callbacks:
            run_config["callbacks"] = callbacks

        try:
            result = await self.graph.ainvoke(initial_state, config=run_config)
            self._stats_handler.finish_trace(status="success")
            return result
        except Exception as e:
            self._stats_handler.finish_trace(status="error", error_msg=str(e)[:500])
            raise
```

**Step 2: 验证导入**

Run: `cd /c/Users/30262/Project/Anima && python -c "from anima.orchestration.graph.orchestrator import LangGraphOrchestrator; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/animetta/orchestration/graph/orchestrator.py
git commit -m "feat: 集成 StatsCallbackHandler 到 Orchestrator"
```

---

### Task 4: HTTP API 路由

**Files:**
- Create: `src/animetta/orchestration/server/stats_api.py`
- Modify: `src/animetta/orchestration/server/websocket.py`

**Step 1: 创建 Stats API 路由**

```python
"""Pipeline 统计 HTTP API"""

import json
from typing import Optional
from loguru import logger

from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
from starlette.routing import Route

from ..graph.stats_store import get_stats_store


async def stats_overview(request: Request) -> JSONResponse:
    """GET /api/stats/overview"""
    try:
        store = await get_stats_store()
        data = await store.get_overview()
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[StatsAPI] overview 失败: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_nodes(request: Request) -> JSONResponse:
    """GET /api/stats/nodes"""
    try:
        store = await get_stats_store()
        data = await store.get_node_stats()
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[StatsAPI] nodes 失败: {e}")
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
        logger.error(f"[StatsAPI] traces 失败: {e}")
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
        logger.error(f"[StatsAPI] trace_detail 失败: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def stats_dashboard(request: Request) -> HTMLResponse:
    """GET /stats/ — 仪表盘页面"""
    from pathlib import Path
    dashboard_path = Path(__file__).parent.parent.parent.parent.parent / "frontend" / "stats" / "index.html"
    if dashboard_path.exists():
        return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found</h1><p>请先构建前端: frontend/stats/index.html</p>")


def get_stats_routes():
    """返回统计 API 的路由列表"""
    return [
        Route("/api/stats/overview", stats_overview),
        Route("/api/stats/nodes", stats_nodes),
        Route("/api/stats/traces", stats_traces),
        Route("/api/stats/traces/{trace_id}", stats_trace_detail),
        Route("/stats/", stats_dashboard),
    ]
```

**Step 2: 修改 websocket.py 挂载路由**

在 `websocket.py` 中，将纯 `socketio.ASGIApp` 替换为 Starlette 路由包装。修改 `__init__` 方法中的 `self.asgi_app` 赋值：

在文件顶部导入区域添加：

```python
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from .stats_api import get_stats_routes
```

替换 `self.asgi_app = socketio.ASGIApp(self.sio)` 为：

```python
        # 创建带 API 路由的 ASGI 应用
        sio_app = socketio.ASGIApp(self.sio)
        stats_routes = get_stats_routes()

        self.asgi_app = Starlette(
            routes=stats_routes + [Mount("/", app=sio_app)],
            lifespan=None,
        )
```

**Step 3: 验证服务能启动**

Run: `cd /c/Users/30262/Project/Anima && python -c "from anima.orchestration.server.websocket import WebSocketServer; s = WebSocketServer(); print('ASGI app type:', type(s.asgi_app)); print('OK')"`
Expected: `ASGI app type: <class 'starlette.applications.Starlette'>` 和 `OK`

**Step 4: Commit**

```bash
git add src/animetta/orchestration/server/stats_api.py src/animetta/orchestration/server/websocket.py
git commit -m "feat: 添加 Stats HTTP API 和 Starlette 路由挂载"
```

---

### Task 5: 添加 .gitignore 和依赖

**Files:**
- Modify: `.gitignore`
- Check: `requirements.txt` 是否已有 `aiosqlite`

**Step 1: 添加 data/stats.db 到 .gitignore**

在 `.gitignore` 中添加：

```
# Stats database
data/stats.db
data/stats.db-*
```

**Step 2: 检查/添加 aiosqlite 依赖**

Run: `cd /c/Users/30262/Project/Anima && grep -q aiosqlite requirements.txt && echo "FOUND" || echo "NOT FOUND"`

如果输出 `NOT FOUND`，追加到 `requirements.txt`：

```
aiosqlite>=0.20.0
```

**Step 3: 安装依赖**

Run: `cd /c/Users/30262/Project/Anima && pip install aiosqlite`

**Step 4: Commit**

```bash
git add .gitignore requirements.txt
git commit -m "chore: 添加 stats.db 到 .gitignore, 添加 aiosqlite 依赖"
```

---

### Task 6: 前端 Dashboard

**Files:**
- Create: `frontend/stats/index.html`
- Create: `frontend/stats/stats.js`
- Create: `frontend/stats/stats.css`

**Step 1: 创建 HTML 页面**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Anima Pipeline Dashboard</title>
    <link rel="stylesheet" href="stats.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
</head>
<body>
    <header>
        <h1>Anima Pipeline Dashboard</h1>
        <span class="auto-refresh">Auto-refresh: <span id="refresh-status">ON</span></span>
    </header>

    <section class="kpi-cards">
        <div class="card">
            <div class="card-label">Total Requests</div>
            <div class="card-value" id="total-requests">-</div>
        </div>
        <div class="card">
            <div class="card-label">Success Rate</div>
            <div class="card-value" id="success-rate">-</div>
        </div>
        <div class="card">
            <div class="card-label">P95 Latency</div>
            <div class="card-value" id="p95-latency">-</div>
        </div>
    </section>

    <section class="chart-section">
        <h2>Node Performance</h2>
        <div class="chart-container">
            <canvas id="node-chart"></canvas>
        </div>
    </section>

    <section class="traces-section">
        <h2>Recent Traces</h2>
        <div class="traces-table-wrap">
            <table id="traces-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Type</th>
                        <th>Input</th>
                        <th>Duration</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="traces-body"></tbody>
            </table>
        </div>
    </section>

    <!-- Trace Detail Modal -->
    <div id="trace-modal" class="modal hidden">
        <div class="modal-content">
            <div class="modal-header">
                <h2>Trace Detail</h2>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="trace-detail"></div>
        </div>
    </div>

    <script src="stats.js"></script>
</body>
</html>
```

**Step 2: 创建 CSS**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    padding: 24px;
}

header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}

header h1 { font-size: 24px; font-weight: 600; }
.auto-refresh { font-size: 13px; color: #94a3b8; }

.kpi-cards {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 24px;
}

.card {
    background: #1e293b;
    border-radius: 8px;
    padding: 20px;
}

.card-label { font-size: 13px; color: #94a3b8; margin-bottom: 8px; }
.card-value { font-size: 32px; font-weight: 700; color: #f8fafc; }

.chart-section {
    background: #1e293b;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 24px;
}

.chart-section h2 { font-size: 16px; margin-bottom: 16px; }
.chart-container { height: 300px; }

.traces-section {
    background: #1e293b;
    border-radius: 8px;
    padding: 20px;
}

.traces-section h2 { font-size: 16px; margin-bottom: 16px; }

.traces-table-wrap { overflow-x: auto; }

table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 8px 12px; color: #94a3b8; font-size: 13px; border-bottom: 1px solid #334155; }
td { padding: 8px 12px; font-size: 14px; border-bottom: 1px solid #1e293b; }
tr:hover { background: #334155; cursor: pointer; }
tr.trace-row { transition: background 0.15s; }

.status-success { color: #4ade80; }
.status-error { color: #f87171; }

/* Modal */
.modal {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.6);
    display: flex; align-items: center; justify-content: center;
    z-index: 100;
}
.modal.hidden { display: none; }
.modal-content {
    background: #1e293b;
    border-radius: 12px;
    padding: 24px;
    width: 80%;
    max-width: 800px;
    max-height: 80vh;
    overflow-y: auto;
}
.modal-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 16px;
}
.modal-header h2 { font-size: 18px; }
.modal-close {
    background: none; border: none; color: #94a3b8; font-size: 24px; cursor: pointer;
}
.modal-close:hover { color: #f8fafc; }

/* Trace detail spans */
.span-list { list-style: none; }
.span-item {
    background: #0f172a;
    border-radius: 6px;
    padding: 12px;
    margin-bottom: 8px;
    display: grid;
    grid-template-columns: 120px 100px 1fr;
    gap: 12px;
    align-items: center;
}
.span-name { font-weight: 600; }
.span-duration { color: #38bdf8; font-variant-numeric: tabular-nums; }
.span-summary { font-size: 13px; color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.trace-meta {
    background: #0f172a;
    border-radius: 6px;
    padding: 12px;
    margin-bottom: 16px;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
}
.trace-meta-item label { display: block; font-size: 12px; color: #94a3b8; }
.trace-meta-item span { font-size: 14px; }
```

**Step 3: 创建 JS**

```javascript
const API_BASE = window.location.origin;
let refreshTimer = null;

// === KPI ===
async function fetchOverview() {
    const res = await fetch(`${API_BASE}/api/stats/overview`);
    const data = await res.json();

    document.getElementById("total-requests").textContent =
        data.total_requests.toLocaleString();
    document.getElementById("success-rate").textContent =
        data.success_rate + "%";
    document.getElementById("p95-latency").textContent =
        data.p95_duration_ms ? data.p95_duration_ms.toFixed(0) + "ms" : "-";
}

// === Chart ===
let nodeChart = null;

async function fetchNodeStats() {
    const res = await fetch(`${API_BASE}/api/stats/nodes`);
    const data = await res.json();

    const labels = data.map(d => d.node_name);
    const durations = data.map(d => d.avg_duration_ms);
    const errors = data.map(d => d.error_count);

    if (nodeChart) {
        nodeChart.data.labels = labels;
        nodeChart.data.datasets[0].data = durations;
        nodeChart.data.datasets[1].data = errors;
        nodeChart.update();
        return;
    }

    nodeChart = new Chart(document.getElementById("node-chart"), {
        type: "bar",
        data: {
            labels,
            datasets: [
                {
                    label: "Avg Duration (ms)",
                    data: durations,
                    backgroundColor: "#38bdf8",
                    borderRadius: 4,
                },
                {
                    label: "Errors",
                    data: errors,
                    backgroundColor: "#f87171",
                    borderRadius: 4,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: "y",
            scales: {
                x: { grid: { color: "#334155" }, ticks: { color: "#94a3b8" } },
                y: { grid: { color: "#334155" }, ticks: { color: "#94a3b8" } },
            },
            plugins: {
                legend: { labels: { color: "#e2e8f0" } },
            },
        },
    });
}

// === Traces ===
async function fetchTraces() {
    const res = await fetch(`${API_BASE}/api/stats/traces?limit=50`);
    const data = await res.json();

    const tbody = document.getElementById("traces-body");
    tbody.innerHTML = "";

    data.forEach(trace => {
        const tr = document.createElement("tr");
        tr.className = "trace-row";
        tr.onclick = () => showTraceDetail(trace.trace_id);

        const time = trace.created_at
            ? new Date(trace.created_at + "Z").toLocaleTimeString()
            : "-";
        const statusClass = trace.status === "success" ? "status-success" : "status-error";

        tr.innerHTML = `
            <td>${time}</td>
            <td>${trace.input_type}</td>
            <td>${escapeHtml(trace.user_text || "-")}</td>
            <td>${trace.total_duration_ms ? trace.total_duration_ms.toFixed(0) + "ms" : "-"}</td>
            <td class="${statusClass}">${trace.status}</td>
        `;
        tbody.appendChild(tr);
    });
}

// === Trace Detail ===
async function showTraceDetail(traceId) {
    const res = await fetch(`${API_BASE}/api/stats/traces/${traceId}`);
    const data = await res.json();
    if (data.error) { alert(data.error); return; }

    const detail = document.getElementById("trace-detail");
    const time = data.created_at
        ? new Date(data.created_at + "Z").toLocaleString()
        : "-";

    detail.innerHTML = `
        <div class="trace-meta">
            <div class="trace-meta-item">
                <label>Trace ID</label>
                <span>${data.trace_id.slice(0, 8)}...</span>
            </div>
            <div class="trace-meta-item">
                <label>Total Duration</label>
                <span>${data.total_duration_ms ? data.total_duration_ms.toFixed(0) + "ms" : "-"}</span>
            </div>
            <div class="trace-meta-item">
                <label>Status</label>
                <span class="${data.status === 'success' ? 'status-success' : 'status-error'}">${data.status}</span>
            </div>
            <div class="trace-meta-item">
                <label>Time</label>
                <span>${time}</span>
            </div>
        </div>
        <h3>Spans (${data.spans.length})</h3>
        <ul class="span-list">
            ${data.spans.map(s => `
                <li class="span-item">
                    <span class="span-name">${s.node_name}</span>
                    <span class="span-duration">${s.duration_ms ? s.duration_ms.toFixed(1) + "ms" : "-"}</span>
                    <span class="span-summary">${escapeHtml(s.output_summary || s.input_summary || "-")}</span>
                </li>
            `).join("")}
        </ul>
    `;

    document.getElementById("trace-modal").classList.remove("hidden");
}

function closeModal() {
    document.getElementById("trace-modal").classList.add("hidden");
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// === Auto Refresh ===
async function refreshAll() {
    await Promise.all([fetchOverview(), fetchNodeStats(), fetchTraces()]);
}

// Init
refreshAll();
refreshTimer = setInterval(refreshAll, 5000);
```

**Step 4: 验证前端文件可访问**

检查文件存在：
- `frontend/stats/index.html`
- `frontend/stats/stats.css`
- `frontend/stats/stats.js`

**Step 5: Commit**

```bash
git add frontend/stats/index.html frontend/stats/stats.css frontend/stats/stats.js
git commit -m "feat: 添加 Pipeline Dashboard 前端页面"
```

---

### Task 7: 端到端验证

**Step 1: 启动后端**

Run: `cd /c/Users/30262/Project/Anima && python -m anima.core.socketio_server`

Expected: 服务启动无报错，日志中看到 `统计 handler 已注入`

**Step 2: 发送测试请求**

另开终端，用 curl 或浏览器发送 WebSocket 文本消息（或通过前端 Chat 窗口）。

**Step 3: 验证 API 数据**

Run: `curl http://localhost:12394/api/stats/overview`
Expected: `{"total_requests": 1, "success_rate": 100.0, "avg_duration_ms": ..., "p95_duration_ms": ...}`

Run: `curl http://localhost:12394/api/stats/nodes`
Expected: 各节点统计数组

Run: `curl http://localhost:12394/api/stats/traces`
Expected: 最近请求列表

**Step 4: 验证 Dashboard 页面**

浏览器打开 `http://localhost:12394/stats/`
Expected: 看到深色主题 Dashboard，KPI 卡片有数据，柱状图显示节点耗时，表格显示最近请求

**Step 5: Final Commit**

```bash
git add -A
git commit -m "feat: Pipeline Stats Dashboard 完成"
```

---

## 文件变更清单

| 操作 | 文件 |
|------|------|
| 新增 | `src/animetta/orchestration/graph/stats_store.py` |
| 新增 | `src/animetta/orchestration/graph/stats_handler.py` |
| 新增 | `src/animetta/orchestration/server/stats_api.py` |
| 修改 | `src/animetta/orchestration/graph/orchestrator.py`（注入 handler） |
| 修改 | `src/animetta/orchestration/server/websocket.py`（挂载 API 路由） |
| 修改 | `.gitignore`（添加 data/stats.db） |
| 可能修改 | `requirements.txt`（添加 aiosqlite） |
| 新增 | `frontend/stats/index.html` |
| 新增 | `frontend/stats/stats.css` |
| 新增 | `frontend/stats/stats.js` |
