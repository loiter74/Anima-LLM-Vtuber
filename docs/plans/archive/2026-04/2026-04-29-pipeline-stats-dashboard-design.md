# Pipeline Stats Dashboard 设计文档

## 目标

为 Anima 的 LangGraph 调用链路建立可观测性统计面板，采集各节点执行耗时、调用统计和链路溯源数据。

**优先级：**
- 面试项目展示（60%）—— 体现全链路可观测性设计能力
- 开发调试工具（20%）—— 快速定位性能瓶颈
- 运行时监控（20%）—— 了解服务健康状态

## 方案选型

**选定：LangGraph Callback Handler 模式**

继承 `BaseCallbackHandler`，监听节点生命周期事件（`on_chain_start` / `on_chain_end` / `on_chain_error`），自动采集数据。

**为什么选 Callback 而不是装饰器：**
- 零侵入 —— 不修改任何现有节点代码
- 与已有 LangFuse 集成同一模式（`observability.py` 中 `CallbackHandler`）
- 体现关注点分离设计原则（业务逻辑 vs 可观测性）

**为什么不用 Prometheus + Grafana：**
- 引入重依赖，不利于 demo
- SQLite 足够满足需求，和项目风格一致

## 数据模型

采用 OpenTelemetry 的 Trace/Span 模型：

```
Trace (一次完整请求)
├── Span: asr_node      (12ms)
├── Span: llm_node      (850ms)
├── Span: tts_node      (320ms)
├── Span: emotion_node  (5ms)
└── Span: output_node   (8ms)
```

`parent_span_id` 字段为多 Agent 扩展预留，当前为 NULL。

## 模块设计

### 1. 数据采集 —— StatsCallbackHandler

**文件：** `src/animetta/orchestration/graph/stats_handler.py`

继承 `langchain_core.callbacks.BaseCallbackHandler`，监听 LangGraph 节点生命周期：

- `on_chain_start` → 记录 start_time，创建 Span
- `on_chain_end` → 计算 duration，存入 SQLite
- `on_chain_error` → 记录 error

**Trace 生命周期：**
- 在 orchestrator `_run_graph()` 前后生成 trace 记录
- 通过 `config["configurable"]["trace_id"]` 传递给各 Span

### 2. 数据存储 —— SQLite

**文件：** `src/animetta/orchestration/graph/stats_store.py`

```sql
CREATE TABLE traces (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT,
    input_type TEXT,           -- "text" / "audio"
    user_text TEXT,            -- 截断前 100 字
    total_duration_ms REAL,
    status TEXT,               -- "success" / "error"
    error_msg TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT REFERENCES traces(trace_id),
    parent_span_id TEXT,       -- 多 Agent 预留，当前为 NULL
    node_name TEXT,            -- "asr", "llm", "tts" 等
    duration_ms REAL,
    status TEXT,               -- "success" / "error"
    input_summary TEXT,        -- 节点输入摘要
    output_summary TEXT,       -- 节点输出摘要
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_traces_created ON traces(created_at DESC);
CREATE INDEX idx_spans_trace ON spans(trace_id);
CREATE INDEX idx_spans_node ON spans(node_name);
```

**数据库文件：** `data/stats.db`（gitignore 中排除）

### 3. 后端 API —— FastAPI 路由

**文件：** `src/animetta/orchestration/server/routes.py`（扩展现有路由）

```
GET /api/stats/overview         → 总览（总请求数、成功率、P50/P95 延迟）
GET /api/stats/nodes            → 各节点统计（平均耗时、调用次数、错误率）
GET /api/stats/traces           → 最近请求列表（分页，默认 50 条）
GET /api/stats/traces/{trace_id} → 某次请求的完整链路详情（含所有 Span）
```

### 4. 前端 Dashboard —— 独立 Web 页面

**文件：** `frontend/stats/` 目录

纯 HTML + vanilla JS + Chart.js（与项目前端风格一致）。

**页面布局：**

```
┌─────────────────────────────────────────────────┐
│  Anima Pipeline Dashboard                       │
├──────────────┬──────────────┬───────────────────┤
│  总请求数     │  成功率       │  P95 延迟         │
│    1,247     │   98.3%      │   1,520ms         │
├──────────────┴──────────────┴───────────────────┤
│  [各节点平均耗时柱状图]                           │
│  ████████████████ LLM   850ms                   │
│  ██████           TTS   320ms                   │
│  █                ASR    12ms                    │
├─────────────────────────────────────────────────┤
│  [最近请求列表]                                  │
│  #1247  文本输入  "你好"   1195ms  ✅  10:23:45  │
│  #1246  语音输入  "天气"   1520ms  ✅  10:22:30  │
│  点击某行 → 展开完整链路详情                      │
└─────────────────────────────────────────────────┘
```

**功能：**
- 顶部三个 KPI 卡片
- 节点耗时柱状图（Chart.js）
- 最近请求列表，点击展开链路详情（每个节点的输入/输出/耗时）
- 自动刷新（5s 轮询）

## 集成方式

在 `orchestrator.py` 的 `_run_graph()` 中注入 StatsCallbackHandler：

```python
# 现有代码
run_config["callbacks"] = [langfuse_handler]

# 新增 stats handler（并行工作）
run_config["callbacks"].append(stats_handler)
```

无需修改任何节点文件。

## 多 Agent 扩展预留

`spans.parent_span_id` 字段支持层级嵌套：

```
Trace (用户请求)
├── Span: orchestrator (主Agent, parent_span_id=NULL)
│   ├── Span: game_agent (parent_span_id=orchestrator的span_id)
│   │   ├── Span: perceive
│   │   └── Span: act
│   └── Span: chat_agent (parent_span_id=orchestrator的span_id)
│       ├── Span: llm_node
│       └── Span: tts_node
```

当前 `parent_span_id` 写入 NULL，未来多 Agent 时填入父 span 的 ID 即可，无需改表结构。

## 文件变更清单

| 操作 | 文件 |
|------|------|
| 新增 | `src/animetta/orchestration/graph/stats_handler.py` |
| 新增 | `src/animetta/orchestration/graph/stats_store.py` |
| 修改 | `src/animetta/orchestration/graph/orchestrator.py`（注入 handler） |
| 修改 | `src/animetta/orchestration/server/routes.py`（新增 API 路由） |
| 新增 | `frontend/stats/index.html` |
| 新增 | `frontend/stats/stats.js` |
| 新增 | `frontend/stats/stats.css` |
