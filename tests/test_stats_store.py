from __future__ import annotations
"""Pipeline Stats 自动化测试

覆盖：StatsStore CRUD、StatsCallbackHandler 采集、Stats API 端到端
"""

import asyncio
import pytest
import pytest_asyncio
import uuid
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from animetta.orchestration.server.stats_api import get_stats_routes
from animetta.orchestration.graph.stats_store import StatsStore, get_stats_store
from animetta.orchestration.graph import stats_store
from animetta.orchestration.graph.stats_handler import StatsCallbackHandler, KNOWN_NODES

# 确保项目 src 在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ============================================================
# StatsStore 单元测试
# ============================================================

class TestStatsStore:
    """测试 SQLite 存储层"""

    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        """每个测试用独立的临时数据库"""

        db_path = str(tmp_path / "test_stats.db")
        s = StatsStore(db_path=db_path)
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_init_creates_tables(self, store):
        """数据库初始化应创建 traces 和 spans 表"""
        cursor = await store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('traces', 'spans')"
        )
        tables = [row[0] for row in await cursor.fetchall()]
        assert "traces" in tables
        assert "spans" in tables

    @pytest.mark.asyncio
    async def test_create_and_finish_trace(self, store):
        """创建并完成一个 trace"""
        trace_id = str(uuid.uuid4())

        await store.create_trace(trace_id, "session-1", "text", "你好世界")
        await store.finish_trace(trace_id, 1234.5, "success")

        detail = await store.get_trace_detail(trace_id)
        assert detail is not None
        assert detail["session_id"] == "session-1"
        assert detail["input_type"] == "text"
        assert detail["user_text"] == "你好世界"
        assert detail["total_duration_ms"] == 1234.5
        assert detail["status"] == "success"

    @pytest.mark.asyncio
    async def test_trace_text_truncated(self, store):
        """user_text 应截断到 100 字符"""
        trace_id = str(uuid.uuid4())
        long_text = "a" * 200

        await store.create_trace(trace_id, "s", "text", long_text)
        detail = await store.get_trace_detail(trace_id)
        assert len(detail["user_text"]) == 100

    @pytest.mark.asyncio
    async def test_error_trace(self, store):
        """错误 trace 存储 error_msg"""
        trace_id = str(uuid.uuid4())

        await store.create_trace(trace_id, "s", "text", "test")
        await store.finish_trace(trace_id, 500.0, "error", "LLM 超时")

        detail = await store.get_trace_detail(trace_id)
        assert detail["status"] == "error"
        assert "LLM 超时" in detail["error_msg"]

    @pytest.mark.asyncio
    async def test_create_and_finish_span(self, store):
        """创建并完成一个 span"""
        trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())

        await store.create_trace(trace_id, "s", "text", "test")
        await store.create_span(span_id, trace_id, "llm", input_summary="你好")
        await store.finish_span(span_id, 850.3, "success", "你好呀")

        detail = await store.get_trace_detail(trace_id)
        assert len(detail["spans"]) == 1
        span = detail["spans"][0]
        assert span["node_name"] == "llm"
        assert span["duration_ms"] == 850.3
        assert span["status"] == "success"
        assert span["input_summary"] == "你好"
        assert span["output_summary"] == "你好呀"

    @pytest.mark.asyncio
    async def test_span_with_parent(self, store):
        """span 支持 parent_span_id"""
        trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())
        parent_id = str(uuid.uuid4())

        await store.create_trace(trace_id, "s", "text", "test")
        await store.create_span(span_id, trace_id, "llm", parent_span_id=parent_id)

        detail = await store.get_trace_detail(trace_id)
        assert detail["spans"][0]["parent_span_id"] == parent_id

    @pytest.mark.asyncio
    async def test_get_overview_empty(self, store):
        """无数据时 overview 返回零值"""
        overview = await store.get_overview()
        assert overview["total_requests"] == 0
        assert overview["success_rate"] == 0
        assert overview["p95_duration_ms"] == 0

    @pytest.mark.asyncio
    async def test_get_overview_with_data(self, store):
        """有数据时 overview 正确计算"""
        for i in range(5):
            tid = str(uuid.uuid4())
            await store.create_trace(tid, "s", "text", f"test{i}")
            await store.finish_trace(tid, 100.0 + i * 100, "success")

        overview = await store.get_overview()
        assert overview["total_requests"] == 5
        assert overview["success_rate"] == 100.0
        assert overview["avg_duration_ms"] == 300.0

    @pytest.mark.asyncio
    async def test_get_node_stats(self, store):
        """节点统计聚合"""
        trace_id = str(uuid.uuid4())
        await store.create_trace(trace_id, "s", "text", "test")

        for node, dur in [("llm", 800), ("tts", 300), ("llm", 900)]:
            sid = str(uuid.uuid4())
            await store.create_span(sid, trace_id, node)
            await store.finish_span(sid, dur)

        stats = await store.get_node_stats()
        assert len(stats) == 2
        # 按平均耗时降序
        assert stats[0]["node_name"] == "llm"
        assert stats[0]["call_count"] == 2
        assert stats[0]["avg_duration_ms"] == 850.0
        assert stats[1]["node_name"] == "tts"

    @pytest.mark.asyncio
    async def test_get_recent_traces_pagination(self, store):
        """分页查询"""
        for i in range(5):
            tid = str(uuid.uuid4())
            await store.create_trace(tid, "s", "text", f"test{i}")
            await store.finish_trace(tid, 100.0, "success")

        page1 = await store.get_recent_traces(limit=3, offset=0)
        page2 = await store.get_recent_traces(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_get_trace_detail_not_found(self, store):
        """不存在的 trace 返回 None"""
        result = await store.get_trace_detail("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_get_stats_store(self, tmp_path):
        """并发调用 get_stats_store 不应竞态"""

        # 重置单例
        stats_store._store = None

        db_path = str(tmp_path / "concurrent_test.db")

        original_cls = stats_store.StatsStore

        class TestStore(original_cls):
            pass

        # 用临时路径创建
        async def get_test_store():
            if stats_store._store is not None:
                return stats_store._store
            async with stats_store._store_lock:
                if stats_store._store is None:
                    s = original_cls(db_path=db_path)
                    await s.init()
                    stats_store._store = s
            return stats_store._store

        # 并发 10 个协程
        stores = await asyncio.gather(*[get_test_store() for _ in range(10)])

        # 所有应返回同一个实例
        assert all(s is stores[0] for s in stores)

        # 清理
        await stats_store._store.close()
        stats_store._store = None


# ============================================================
# StatsCallbackHandler 单元测试
# ============================================================

class TestStatsCallbackHandler:
    """测试 Callback Handler 采集逻辑"""

    def test_known_nodes_filter(self):
        """已知节点名应被识别"""

        assert "llm" in KNOWN_NODES
        assert "tts" in KNOWN_NODES
        assert "asr" in KNOWN_NODES
        assert "emotion" in KNOWN_NODES
        assert "output" in KNOWN_NODES
        assert "tools" in KNOWN_NODES
        assert "_RouteInput" not in KNOWN_NODES
        assert "_ShouldUseTools" not in KNOWN_NODES

    def test_handler_instantiation(self):
        """Handler 应正确初始化"""

        handler = StatsCallbackHandler()
        assert handler._active_spans == {}
        assert handler._trace_id is None

    def test_start_trace_returns_id(self):
        """start_trace 应返回 UUID 字符串"""

        handler = StatsCallbackHandler()
        trace_id = handler.start_trace("session-1", "text", "你好")
        assert isinstance(trace_id, str)
        assert len(trace_id) == 36  # UUID format

    def test_summarize_input(self):
        """输入摘要应截断到 200 字符"""

        state = {"user_text": "a" * 300}
        result = StatsCallbackHandler._summarize_input("llm", {"state": state})
        assert len(result) == 200

    def test_summarize_output(self):
        """输出摘要优先取 response_text"""

        outputs = {"response_text": "你好呀", "emotion": "happy"}
        result = StatsCallbackHandler._summarize_output("llm", outputs)
        assert result == "你好呀"


# ============================================================
# Stats API 端到端测试
# ============================================================

class TestStatsAPI:
    """测试 HTTP API 端点"""

    @pytest_asyncio.fixture
    async def client(self, tmp_path):
        """创建测试用 httpx 客户端 + 临时数据库"""
        import httpx
        from starlette.applications import Starlette
        from starlette.routing import Mount
        import socketio

        # 重置单例
        stats_store._store = None

        db_path = str(tmp_path / "api_test.db")

        # 创建测试用的 store
        store = stats_store.StatsStore(db_path=db_path)
        await store.init()
        stats_store._store = store

        # 创建 Starlette 测试 app（只有 API 路由，不挂 Socket.IO）
        routes = get_stats_routes()
        # 过滤掉 /stats/ 静态文件路由（测试不需要）
        api_routes = [r for r in routes if not isinstance(r, Mount)]
        app = Starlette(routes=api_routes)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

        # 清理
        await store.close()
        stats_store._store = None

    @pytest.mark.asyncio
    async def test_overview_empty(self, client):
        """空数据库 overview"""
        resp = await client.get("/api/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 0
        assert data["success_rate"] == 0

    @pytest.mark.asyncio
    async def test_nodes_empty(self, client):
        """空数据库 nodes"""
        resp = await client.get("/api/stats/nodes")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_traces_empty(self, client):
        """空数据库 traces"""
        resp = await client.get("/api/stats/traces")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_trace_detail_not_found(self, client):
        """不存在的 trace"""
        resp = await client.get("/api/stats/traces/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_full_flow(self, client):
        """完整流程：写入数据 → 查询 API"""

        store = await get_stats_store()

        # 模拟一次完整请求
        trace_id = str(uuid.uuid4())
        await store.create_trace(trace_id, "session-1", "text", "你好")

        for node, dur in [("llm", 800), ("tts", 300), ("emotion", 5), ("output", 8)]:
            span_id = str(uuid.uuid4())
            await store.create_span(span_id, trace_id, node, input_summary="test")
            await store.finish_span(span_id, dur, "success", f"{node} done")

        await store.finish_trace(trace_id, 1113.0, "success")

        # 验证 overview
        resp = await client.get("/api/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 1
        assert data["success_rate"] == 100.0

        # 验证 nodes
        resp = await client.get("/api/stats/nodes")
        assert resp.status_code == 200
        nodes = resp.json()
        assert len(nodes) == 4
        assert nodes[0]["node_name"] == "llm"  # 按耗时降序

        # 验证 traces 列表
        resp = await client.get("/api/stats/traces")
        assert resp.status_code == 200
        traces = resp.json()
        assert len(traces) == 1
        assert traces[0]["user_text"] == "你好"

        # 验证 trace detail
        resp = await client.get(f"/api/stats/traces/{trace_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["status"] == "success"
        assert len(detail["spans"]) == 4
        assert detail["total_duration_ms"] == 1113.0
