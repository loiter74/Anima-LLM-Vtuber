# Animetta HTTP REST 接口文档

**协议**: HTTP REST（Starlette ASGI）

> Socket.IO 实时双向事件（对话、语音、人格、记忆等）参考 [socket-api.md](socket-api.md)。

---

## 服务端点

| 环境 | HTTP |
|------|------|
| **默认** | `http://localhost:12394` |
| **Docker** | `http://localhost`（nginx 代理到 12394） |

---

## 基础设施端点

### `GET /health`

**用途**: 服务健康状态检查，用于负载均衡器和监控系统

**请求**: 无参数

**响应**:
```json
{
  "status": "ok",
  "service": "anima",
  "timestamp": 1686652800.0,
  "gpu": {
    "available": true,
    "name": "NVIDIA GeForce RTX 4090",
    "memory_total_mb": 24564.0,
    "memory_used_mb": 1024.5,
    "memory_free_mb": 23539.5
  },
  "models": {
    "faster_whisper": "loaded",
    "kokoro_tts": "loaded",
    "live2d_model": "loaded"
  },
  "checks": {
    "database": { "ok": true, "message": "SQLite connected" },
    "chroma": { "ok": true, "message": "ChromaDB ready" },
    "llm": { "ok": true, "message": "LLM provider available" }
  }
}
```

**状态说明**:
- `ok`: 所有组件检查通过
- `degraded`: 部分组件异常，服务可用但性能下降
- `error`: 健康检查本身失败

---

### `GET /metrics`

**用途**: Prometheus 格式的指标数据，用于监控和告警

**响应格式**: Prometheus text format

**示例指标**:
```
# HELP active_sessions Number of active WebSocket sessions
# TYPE active_sessions gauge
active_sessions 5

# HELP llm_tokens_total Total LLM tokens processed
# TYPE llm_tokens_total counter
llm_tokens_total 1234567

# HELP graph_node_duration_seconds Time spent in each graph node
# TYPE graph_node_duration_seconds histogram
graph_node_duration_seconds_bucket{node="llm_node",le="0.1"} 100
```

---

### 静态文件服务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/app/*` | 前端生产构建静态文件（SPA fallback；`/api/*`、`/socket.io/*` 透传后端） |
| GET | `/stats/*` | 统计仪表板前端 |

> `/app/*` 仅在 `frontend/dist` 目录存在时可用。

---

## 业务端点

### 歌唱媒体文件 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/singing/audio/{filename}` | 获取音频文件 |
| GET | `/api/singing/subtitle/{filename}` | 获取字幕文件 |
| GET | `/api/singing/recent` | 获取最近 5 个唱歌记录 |

**`/api/singing/recent` 响应**:
```json
[
  {
    "session_id": "session_123",
    "audio_url": "/api/singing/audio/session_123_final.wav",
    "vocals_url": "/api/singing/audio/session_123_vocals.wav",
    "original_url": "/api/singing/audio/session_123_original.wav",
    "subtitle_url": "/api/singing/subtitle/session_123_lyrics.ass",
    "tts_audio_url": "/api/singing/audio/session_123_tts_final.wav",
    "created_at": "2026-06-13T12:00:00Z",
    "duration_sec": 180.5
  }
]
```

---

## 管理监控端点

### 统计分析

#### `GET /api/stats/overview`

**用途**: 获取管道统计概览

**响应**:
```json
{
  "total_requests": 1234,
  "total_tokens": 567890,
  "avg_response_time_ms": 1500,
  "active_sessions": 5
}
```

#### `GET /api/stats/nodes`

**用途**: 获取各 Graph Node 的性能统计

**响应**:
```json
{
  "nodes": {
    "asr_node": {
      "count": 500,
      "avg_duration_ms": 200,
      "p95_duration_ms": 500
    },
    "llm_node": {
      "count": 1000,
      "avg_duration_ms": 1200,
      "p95_duration_ms": 3000
    }
  }
}
```

---

### 追踪监控

#### `GET /api/stats/traces`

**用途**: 获取最近的 OpenTelemetry 追踪记录

**查询参数**:
- `limit` (int, 默认 50): 返回数量
- `offset` (int, 默认 0): 偏移量

**响应**:
```json
{
  "traces": [
    {
      "trace_id": "abc123def456",
      "status": "ok",
      "total_duration_ms": 2500,
      "created_at": "2026-06-13T12:00:00Z"
    }
  ],
  "total": 100
}
```

#### `GET /api/stats/traces/{trace_id}`

**用途**: 获取特定追踪的详细信息

**响应**:
```json
{
  "trace_id": "abc123def456",
  "status": "ok",
  "total_duration_ms": 2500,
  "created_at": "2026-06-13T12:00:00Z",
  "spans": [
    {
      "span_id": "span_001",
      "parent_span_id": null,
      "name": "process_text",
      "duration_ms": 2500,
      "attributes": {}
    }
  ]
}
```

#### `GET /api/stats/traces/{trace_id}/tree`

**用途**: 获取追踪的树形结构

**响应**:
```json
{
  "trace_id": "abc123def456",
  "total_duration_ms": 2500,
  "status": "ok",
  "created_at": "2026-06-13T12:00:00Z",
  "tree": [
    {
      "span_id": "span_001",
      "name": "process_text",
      "duration_ms": 2500,
      "children": [
        {
          "span_id": "span_002",
          "name": "llm_node",
          "duration_ms": 1200,
          "children": []
        }
      ]
    }
  ]
}
```

---

### 检查报告

#### `GET /api/stats/inspection/latest`

**用途**: 获取最新的健康检查报告

**响应**:
```json
{
  "run_id": "c2ba934e-91c7-42b5-82dc-ef87fb5f76fc",
  "started_at": 1783353518.986623,
  "finished_at": 1783353524.161326,
  "overall_ok": true,
  "checks": {
    "stats_store": {
      "name": "stats_store",
      "ok": true,
      "duration_ms": 2.15,
      "detail": {},
      "error": null
    },
    "chroma": {
      "name": "chroma",
      "ok": true,
      "duration_ms": 0.59,
      "detail": {},
      "error": null
    }
  },
  "created_at": 1783353524.2
}
```

**错误响应** (404):
```json
{
  "error": "No inspection reports yet"
}
```

---

## 附录：数据格式规范

### 音频数据格式

| 属性 | 值 |
|------|-----|
| **采样率** | 16000 Hz |
| **声道** | Mono (单声道) |
| **位深** | 32-bit float |
| **编码** | PCM / Base64（详见 [socket-api.md](socket-api.md)） |

### 时间格式

所有时间戳使用 ISO 8601 格式：
```
2026-06-13T12:00:00Z          # UTC
2026-06-13T20:00:00+08:00     # 带时区
```

### 情感标签

| 标签 | 说明 | Live2D 映射 |
|------|------|-------------|
| `happy` | 开心 | 嘴角上扬 + 眉毛上挑 + 眼睛放大 |
| `sad` | 悲伤 | 嘴角下垂 + 眉毛下压 + 半闭眼 |
| `angry` | 生气 | 紧咬牙关 + 皱眉 + 身体后仰 |
| `surprised` | 惊讶 | 眼睛放大 + 嘴巴张开 |
| `neutral` | 中性 | 默认表情 |
| `thinking` | 思考 | 微微皱眉 + 眼神向上 |

### 人格模式

| 模式 | 说明 |
|------|------|
| `default` | 默认模式，完整的对话流程 |
| `streaming` | 流式模式，更快的响应速度 |

### 记忆页面类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `source` | 原始对话记录 | 每日对话摘要 |
| `entity` | 实体页面 | 人物、宠物、项目 |
| `concept` | 概念页面 | 偏好、兴趣、习惯 |
| `synthesis` | 综合页面 | 跨时间线主题综合 |

---

## 相关文档

- [Socket.IO API](socket-api.md) — Socket.IO 实时事件目录
- [README.md](../../README.md) — 项目概述和架构图
- [Architecture Overview](../architecture/overview.md) — 架构概览
- [AGENTS.md](../../AGENTS.md) — 项目知识库
