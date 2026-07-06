# Animetta 后端接口文档

**生成时间**: 2026-06-13  
**版本**: 2.0  
**协议**: HTTP REST + Socket.IO (WebSocket)

---

## 📋 目录

1. [架构概述](#架构概述)
2. [接口层次划分](#接口层次划分)
3. [第一层：基础设施层](#第一层基础设施层)
4. [第二层：业务核心层](#第二层业务核心层)
5. [第三层：管理监控层](#第三层管理监控层)
6. [附录：数据格式规范](#附录数据格式规范)

---

## 架构概述

### 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| **HTTP 服务器** | Starlette | 轻量级 ASGI 框架（FastAPI 底层） |
| **WebSocket** | python-socketio | 实时双向通信 |
| **ASGI 服务器** | uvicorn | 高性能异步服务器 |
| **编排引擎** | LangGraph | 有向状态图，支持条件路由和工具调用 |

### 通信协议

```
┌─────────────────────────────────────────────────────────────┐
│                      客户端 (Vue 3 Frontend)                │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
    ┌─────────────────┐       ┌─────────────────┐
    │   HTTP REST     │       │  Socket.IO      │
    │   (Starlette)   │       │  (WebSocket)    │
    │                 │       │                 │
    │ • 健康检查      │       │ • 实时对话      │
    │ • 统计数据      │       │ • 语音流        │
    │ • 媒体文件      │       │ • 事件推送      │
    │ • 指标监控      │       │ • 状态同步      │
    └─────────────────┘       └─────────────────┘
```

### 服务端点

| 环境 | HTTP | WebSocket |
|------|------|-----------|
| **默认** | `http://localhost:12394` | `ws://localhost:12394/socket.io/` |
| **Docker** | `http://localhost` | `ws://localhost/socket.io/` |

---

## 接口层次划分

```
┌─────────────────────────────────────────────────────────────┐
│                    第三层：管理监控层                        │
│   统计分析 · 追踪监控 · 检查报告 · 配置管理                 │
├─────────────────────────────────────────────────────────────┤
│                    第二层：业务核心层                        │
│   对话交互 · 语音处理 · 人格管理 · 记忆系统                 │
│   音乐处理 · 直播集成 · 游戏集成                            │
├─────────────────────────────────────────────────────────────┤
│                    第一层：基础设施层                        │
│   健康检查 · 指标监控 · 静态文件服务 · 连接管理             │
└─────────────────────────────────────────────────────────────┘
```

---

## 第一层：基础设施层

### 1.1 健康检查

#### `GET /health`

**用途**: 服务健康状态检查，用于负载均衡器和监控系统

**请求**: 无参数

**响应**:
```json
{
  "status": "ok",                    // "ok" | "degraded" | "error"
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

### 1.2 Prometheus 指标

#### `GET /metrics`

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

### 1.3 静态文件服务

#### `GET /app/*`

**用途**: 前端生产构建静态文件

**说明**: 
- 仅在 `frontend/dist` 目录存在时可用
- 支持 SPA fallback（所有未匹配路径返回 index.html）
- `/api/*` 和 `/socket.io/*` 请求会透传到后端

#### `GET /stats/*`

**用途**: 统计仪表板前端

**说明**: 独立的统计可视化界面

---

### 1.4 Socket.IO 连接管理

#### `connect`

**方向**: 客户端 → 服务器  
**触发**: 自动连接时  
**数据**: 无

**服务器行为**:
1. 创建会话记录 `{connected_at, is_electron}`
2. 发送 `connection-established` 事件
3. 非 Electron 客户端发送 `control` `{text:"start-mic"}`
4. 增加活跃会话计数器

#### `disconnect`

**方向**: 客户端 → 服务器  
**触发**: 断开连接时  
**数据**: 无

**服务器行为**:
1. 注销桌面客户端
2. 清理会话资源
3. 减少活跃会话计数器

#### `connection-established`

**方向**: 服务器 → 客户端  
**触发**: 连接成功后  
**数据**:
```json
{
  "message": "Connected to Animetta",
  "sid": "session_id_123",
  "server_time": "2026-06-13T12:00:00Z"
}
```

---

## 第二层：业务核心层

### 2.1 对话交互

#### `text_input`

**方向**: 客户端 → 服务器  
**触发**: 用户发送文本消息  
**数据**:
```json
{
  "text": "你好，今天天气怎么样？",
  "user_id": "user",           // 可选，默认 "user"
  "from_name": "User"          // 可选，默认 "User"
}
```

**处理流程**:
1. `chat_handlers.on_text_input()` 接收
2. 调用 `LangGraphOrchestrator.process_text()`
3. 经过状态图: `personality → llm → [tools] → tts → emotion → output`
4. 通过 `sentence` 事件流式返回回复

#### `sentence`

**方向**: 服务器 → 客户端  
**触发**: LLM 生成回复时（流式）  
**数据**:
```json
{
  "text": "你好！今天天气",
  "seq": 0,
  "lang": "zh",
  "is_complete": false
}
```

**流式序列**:
```json
{"text": "你好！", "seq": 0, "lang": "zh"}
{"text": "今天天气", "seq": 1, "lang": "zh"}
{"text": "很好呢～", "seq": 2, "lang": "zh"}
{"text": "", "seq": 3, "is_complete": true}  // 结束标记
```

#### `control`

**方向**: 服务器 → 客户端  
**触发**: 对话状态变化  
**数据**:
```json
{
  "signal": "conversation-start"  // "conversation-start" | "conversation-end"
}
```

**或**:
```json
{
  "type": "control",
  "text": "start-mic"            // "start-mic" | "interrupted"
}
```

#### `interrupt_signal`

**方向**: 客户端 → 服务器  
**触发**: 用户中断 AI 回复  
**数据**:
```json
{
  "text": "已听到的文本"          // 可选
}
```

**服务器行为**:
1. 停止 LLM 生成
2. 停止音频播放（发送 `stop_audio`）
3. 发送 `control` `{text:"interrupted"}`

#### `stop_audio`

**方向**: 服务器 → 客户端  
**触发**: 中断或对话结束时  
**数据**: `{}`（空对象）

---

### 2.2 语音处理

#### `raw_audio_data`

**方向**: 客户端 → 服务器  
**触发**: 麦克风录音时（实时流）  
**数据**:
```json
{
  "audio": [0.1, 0.2, -0.1, ...]  // float32 音频数据数组
}
```

**说明**:
- 持续发送，直到用户停止录音
- 服务器使用 VAD（语音活动检测）判断语音边界
- 音频格式：16kHz, mono, float32

#### `mic_audio_end`

**方向**: 客户端 → 服务器  
**触发**: 用户停止录音  
**数据**: `{}`（空对象）

**服务器行为**:
1. 处理剩余音频缓冲
2. 触发 ASR 识别
3. 识别完成后发送 `transcript` 事件

#### `transcript`

**方向**: 服务器 → 客户端  
**触发**: ASR 识别完成  
**数据**:
```json
{
  "text": "你好，今天天气怎么样？",
  "is_final": true
}
```

#### `audio_with_expression`

**方向**: 服务器 → 客户端  
**触发**: TTS 合成完成  
**数据**:
```json
{
  "audio_data": "UklGRi...",        // Base64 编码的音频数据
  "format": "wav",                   // "wav" | "mp3" | "ogg"
  "volumes": [0.1, 0.2, 0.3, ...]   // 音量包络数组（用于唇形同步）
}
```

---

### 2.3 人格管理

#### `get_available_personas`

**方向**: 客户端 → 服务器  
**触发**: 获取可用人格列表  
**数据**: `{}`（空对象）  
**回调响应**:
```json
{
  "personas": ["default", "neuro-vtuber", "assistant", "anime"]
}
```

#### `set_persona`

**方向**: 客户端 → 服务器  
**触发**: 切换人格  
**数据**:
```json
{
  "persona_name": "neuro-vtuber"
}
```

**回调响应**:
```json
{
  "error": null                    // null 表示成功，字符串表示错误信息
}
```

#### `set_personality_mode`

**方向**: 客户端 → 服务器  
**触发**: 切换人格模式  
**数据**:
```json
{
  "mode": "default"                // "default" | "streaming"
}
```

**回调响应**:
```json
{
  "error": null
}
```

#### `expression`

**方向**: 服务器 → 客户端  
**触发**: 情感分析完成  
**数据**:
```json
{
  "emotion": "happy"               // "happy" | "sad" | "angry" | "surprised" | "neutral" | "thinking"
}
```

#### `live2d.action`

**方向**: 服务器 → 客户端  
**触发**: Live2D 动作触发  
**数据**:
```json
{
  "type": "motion",
  "group": "Idle",                 // Live2D 动作组
  "index": 0                       // 动作索引
}
```

---

### 2.4 记忆系统

#### `memory_organize`

**方向**: 客户端 → 服务器  
**触发**: 手动整理记忆  
**数据**: `{}`（空对象）

**服务器行为**:
1. 运行 V2 记忆代谢（metabolism tick）
2. 编译 RAW → EPISODIC 层
3. 通过进度事件反馈状态

#### `memory.organize.progress`

**方向**: 服务器 → 客户端  
**触发**: 整理进度更新  
**数据**:
```json
{
  "text": "Running metabolism tick...",
  "progress": 30                   // 0-100
}
```

#### `memory.organize.result`

**方向**: 服务器 → 客户端  
**触发**: 整理完成  
**数据**:
```json
{
  "status": "ok",                  // "ok" | "error"
  "message": "Memory organized"
}
```

#### `get_wiki_pages`

**方向**: 客户端 → 服务器  
**触发**: 获取记忆页面列表  
**数据**:
```json
{
  "session_id": "default"
}
```

**回调响应**:
```json
{
  "pages": [
    {
      "path": "atom_id_123",
      "title": "用户喜欢猫",
      "content": "用户表达了对猫的喜爱...",
      "page_type": "entity",       // "source" | "entity" | "concept" | "synthesis"
      "tags": ["preference", "pets"],
      "updated_at": "2026-06-13T12:00:00Z"
    }
  ]
}
```

---

### 2.5 音乐处理

#### `sing:process`

**方向**: 客户端 → 服务器  
**触发**: 开始音乐处理  
**数据**:
```json
{
  "url": "https://www.bilibili.com/video/BV1xx411c7mD",  // Bilibili 视频 URL
  "auto_confirm": true             // 是否自动确认歌词
}
```

**或**:
```json
{
  "file": "audio_file.wav",        // 本地音频文件
  "auto_confirm": false
}
```

#### `sing:progress`

**方向**: 服务器 → 客户端  
**触发**: 处理进度更新  
**数据**:
```json
{
  "stage": "downloading",          // "downloading" | "separating" | "recognizing" | "converting" | "mixing"
  "progress": 50,
  "message": "Downloading audio..."
}
```

#### `sing:complete`

**方向**: 服务器 → 客户端  
**触发**: 处理完成  
**数据**:
```json
{
  "audio_url": "/api/singing/audio/session_123_final.wav",
  "subtitle_url": "/api/singing/subtitle/session_123_lyrics.ass",
  "tts_audio_url": "/api/singing/audio/session_123_tts_final.wav",
  "vocals_url": "/api/singing/audio/session_123_vocals.wav",
  "video_title": "歌曲名称",
  "duration": 180.5,
  "lyrics": [
    {
      "text": "歌词文本",
      "translation": "歌词翻译",
      "start_ms": 1000,
      "end_ms": 3000
    }
  ],
  "volumes": [0.1, 0.2, 0.3, ...]
}
```

#### `sing:error`

**方向**: 服务器 → 客户端  
**触发**: 处理出错  
**数据**:
```json
{
  "error": "Failed to download video: Network error"
}
```

#### `sing:confirm_lyrics`

**方向**: 客户端 → 服务器  
**触发**: 确认歌词  
**数据**:
```json
{
  "ass_content": "[Script Info]\nTitle: Lyrics\n..."
}
```

#### `sing:cancel`

**方向**: 客户端 → 服务器  
**触发**: 取消处理  
**数据**: `{}`（空对象）

#### `sing:lyrics_ready`

**方向**: 服务器 → 客户端  
**触发**: 歌词识别完成，等待用户确认  
**数据**:
```json
{
  "message": "Lyrics ready for review"
}
```

#### `sing:subtitle_line`

**方向**: 服务器 → 客户端  
**触发**: 字幕行同步（实时显示）  
**数据**:
```json
{
  "text": "当前歌词",
  "translation": "当前翻译",
  "lang": "ja",
  "target_lang": "zh"
}
```

#### 唱歌媒体文件 API

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

### 2.6 直播集成（Bilibili）

#### `bilibili.connect`

**方向**: 客户端 → 服务器  
**触发**: 连接直播间  
**数据**:
```json
{
  "room_id": 123456
}
```

#### `bilibili.disconnect`

**方向**: 客户端 → 服务器  
**触发**: 断开直播间  
**数据**: 无

#### `bilibili.update_room`

**方向**: 客户端 → 服务器  
**触发**: 更新房间号  
**数据**:
```json
{
  "room_id": 789012
}
```

#### `danmaku`

**方向**: 服务器 → 客户端  
**触发**: 收到弹幕消息  
**数据**:
```json
{
  "user_name": "观众昵称",
  "message": "弹幕内容",
  "timestamp": 1686652800
}
```

#### `danmaku.status`

**方向**: 服务器 → 客户端  
**触发**: 连接状态变化  
**数据**:
```json
{
  "connected": true,
  "message": "Connected to room 123456"
}
```

#### `danmaku.ai_reply`

**方向**: 服务器 → 客户端  
**触发**: AI 回复弹幕  
**数据**:
```json
{
  "danmaku_text": "你好！",
  "reply_text": "你好呀～欢迎来到直播间！",
  "user_name": "观众昵称",
  "character_name": "Animetta",
  "timestamp": 1686652800
}
```

---

### 2.7 游戏集成（Minecraft）

#### `minecraft.start`

**方向**: 客户端 → 服务器  
**触发**: 启动 Minecraft 机器人  
**数据**: `{}`（空对象）

#### `minecraft.stop`

**方向**: 客户端 → 服务器  
**触发**: 停止 Minecraft 机器人  
**数据**: 无

#### `minecraft.status`

**方向**: 服务器 → 客户端  
**触发**: 机器人状态变化  
**数据**:
```json
{
  "connected": true,               // true | false
  "username": "Animetta_Bot",      // 仅连接时
  "error": "Connection failed"     // 仅错误时
}
```

---

### 2.8 对话历史

#### `fetch_history_list`

**方向**: 客户端 → 服务器  
**触发**: 获取历史会话列表  
**数据**: `{}`（空对象）

**响应**: 通过 `history-list` 事件返回

#### `fetch_history`

**方向**: 客户端 → 服务器  
**触发**: 获取特定会话历史  
**数据**:
```json
{
  "history_uid": "session_123"
}
```

**响应**: 通过 `history-data` 事件返回

#### `clear_history`

**方向**: 客户端 → 服务器  
**触发**: 清除当前会话历史  
**数据**: `{}`（空对象）

**响应**: 通过 `history-cleared` 事件返回

#### `create_new_history`

**方向**: 客户端 → 服务器  
**触发**: 创建新会话  
**数据**: `{}`（空对象）

**响应**: 通过 `new-history-created` 事件返回

---

## 第三层：管理监控层

### 3.1 配置管理

#### `switch_config`

**方向**: 客户端 → 服务器  
**触发**: 切换配置文件  
**数据**:
```json
{
  "config_name": "config_glm"
}
```

**响应**: 通过 `config-switched` 事件返回

#### `set_log_level`

**方向**: 客户端 → 服务器  
**触发**: 设置日志级别  
**数据**:
```json
{
  "level": "DEBUG"                 // "DEBUG" | "INFO" | "WARNING" | "ERROR"
}
```

**响应**: 通过 `log_level_changed` 事件返回

#### `get_config`

**方向**: 客户端 → 服务器  
**触发**: 获取当前配置  
**数据**: `{}`（空对象）

**响应**: 通过 `config_data` 事件返回

#### `heartbeat`

**方向**: 客户端 → 服务器  
**触发**: 心跳保活  
**数据**: `{}`（空对象）

**响应**: 通过 `heartbeat-ack` 事件返回

#### `translation.configure`

**方向**: 客户端 → 服务器  
**触发**: 配置翻译设置  
**数据**:
```json
{
  "enabled": true,
  "target_language": "zh"          // "zh" | "en" | "ja" | "ko"
}
```

**响应**: 通过 `translation.status` 事件返回

#### `subtitle.translation`

**方向**: 服务器 → 客户端  
**触发**: 字幕翻译完成  
**数据**:
```json
{
  "translation": "翻译后的文本",
  "target_lang": "zh"
}
```

---

### 3.2 统计分析 API

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

### 3.3 追踪监控 API

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

### 3.4 检查报告 API

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

### 3.5 桌面客户端事件

#### `desktop_register`

**方向**: 客户端 → 服务器  
**触发**: 注册桌面客户端  
**数据**:
```json
{
  "client_type": "electron"        // "electron" | "desktop"
}
```

**响应**: 通过 `desktop.registered` 事件返回

#### `desktop.registered`

**方向**: 服务器 → 客户端  
**触发**: 注册成功  
**数据**:
```json
{
  "client_id": "client_123",
  "client_type": "electron"
}
```

#### `desktop_live2d_action`

**方向**: 客户端 → 服务器  
**触发**: 触发 Live2D 动作  
**数据**:
```json
{
  "action": "wave",                // Live2D 动作名称
  "params": {}                     // 动作参数
}
```

#### `desktop_chat_message`

**方向**: 客户端 → 服务器  
**触发**: 桌面端发送聊天消息  
**数据**: 同 `text_input`

#### `desktop_voice_start`

**方向**: 客户端 → 服务器  
**触发**: 桌面端开始语音  
**数据**: 无

#### `desktop_voice_stop`

**方向**: 客户端 → 服务器  
**触发**: 桌面端停止语音  
**数据**: 无

---

### 3.6 模型状态事件

#### `model_status`

**方向**: 服务器 → 客户端  
**触发**: 模型加载状态变化  
**数据**:
```json
{
  "model_name": "faster_whisper",
  "status": "loaded",              // "unloaded" | "loading" | "loaded" | "error"
  "progress": 100
}
```

---

### 3.7 错误处理

#### `error`

**方向**: 服务器 → 客户端  
**触发**: 发生错误  
**数据**:
```json
{
  "type": "error",
  "message": "Failed to process request: LLM timeout"
}
```

---

## 附录：数据格式规范

### A.1 音频数据格式

| 属性 | 值 |
|------|-----|
| **采样率** | 16000 Hz |
| **声道** | Mono (单声道) |
| **位深** | 32-bit float |
| **编码** | PCM (raw_audio_data) / Base64 (audio_with_expression) |

### B.1 时间格式

所有时间戳使用 ISO 8601 格式：
```
2026-06-13T12:00:00Z          # UTC
2026-06-13T20:00:00+08:00     # 带时区
```

### C.1 情感标签

| 标签 | 说明 | Live2D 映射 |
|------|------|-------------|
| `happy` | 开心 | 嘴角上扬 + 眉毛上挑 + 眼睛放大 |
| `sad` | 悲伤 | 嘴角下垂 + 眉毛下压 + 半闭眼 |
| `angry` | 生气 | 紧咬牙关 + 皱眉 + 身体后仰 |
| `surprised` | 惊讶 | 眼睛放大 + 嘴巴张开 |
| `neutral` | 中性 | 默认表情 |
| `thinking` | 思考 | 微微皱眉 + 眼神向上 |

### D.1 人格模式

| 模式 | 说明 |
|------|------|
| `default` | 默认模式，完整的对话流程 |
| `streaming` | 流式模式，更快的响应速度 |

### E.1 记忆页面类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `source` | 原始对话记录 | 每日对话摘要 |
| `entity` | 实体页面 | 人物、宠物、项目 |
| `concept` | 概念页面 | 偏好、兴趣、习惯 |
| `synthesis` | 综合页面 | 跨时间线主题综合 |

---

## 前端组件 → 事件映射

### 左侧抽屉 (LeftDrawer)

| 组件 | 按钮/开关 | 触发事件 | 数据 |
|------|----------|----------|------|
| QuickControls | 🔊 Voice 滑块 | 无（本地状态） | - |
| QuickControls | 🎤 Microphone | `raw_audio_data` + `mic_audio_end` | 音频数据 |
| QuickControls | 🧠 Auto Memory | 无（本地状态） | - |
| PersonaCard | - | `get_available_personas` | - |
| SessionStats | - | 无（本地计算） | - |
| MemoryCards | ▶ Send | `text_input` | 话题文本 |
| MemoryCards | ✕ Delete | 无（本地删除） | - |

### 右侧面板 (InteractivePanel)

| 组件 | 按钮/开关 | 触发事件 | 数据 |
|------|----------|----------|------|
| ChatPanel | 发送按钮 | `text_input` | 消息文本 |
| ChatPanel | 语音按钮 | `raw_audio_data` + `mic_audio_end` | 音频数据 |
| ChatPanel | 整理记忆 | `memory_organize` | - |
| SettingsPanel | 切换人格 | `set_persona` | 人格名称 |
| SettingsPanel | 切换模式 | `set_personality_mode` | 模式名称 |
| MemoryPanel | 刷新 | `get_wiki_pages` | session_id |
| PersonalityPanel | 切换人格 | `set_persona` | 人格名称 |
| MusicCard | 开始制作 | `sing:process` | URL |
| MusicCard | 确认歌词 | `sing:confirm_lyrics` | ASS内容 |
| MusicCard | 取消 | `sing:cancel` | - |

---

## 注意事项

1. **所有 Socket.IO 事件都是异步的** - 使用 `socket.emit()` 发送，`socket.on()` 接收
2. **回调模式** - 某些事件支持回调函数作为第三个参数（如 `get_available_personas`）
3. **错误处理** - 监听 `error` 事件处理全局错误
4. **重连机制** - Socket.IO 自动重连，监听 `connect` / `disconnect` 事件
5. **音频流** - `raw_audio_data` 是实时流，需要持续发送
6. **事件命名约定**:
   - 所有事件统一使用点分隔格式：`{module}.{action}`
   - 发送类事件（客户端→服务器）：无动词，如 `chat.text`
   - 接收类事件（服务器→客户端）：结果名词，如 `chat.sentence`
   - 事件名定义在 `config/socket-events.json`，前后端共享
7. **无 OpenAPI 规范** - 由于使用 Starlette（非 FastAPI），没有自动生成的 `/docs` 或 `/openapi.json`

---

## 事件命名迁移指南

### 新旧事件名对照表

#### 客户端→服务器事件

| 旧名称 | 新名称 | 模块 |
|--------|--------|------|
| `text_input` | `chat.text` | chat |
| `raw_audio_data` | `chat.audio` | chat |
| `mic_audio_end` | `chat.audio_end` | chat |
| `interrupt_signal` | `chat.interrupt` | chat |
| `fetch_history_list` | `history.list` | history |
| `fetch_history` | `history.fetch` | history |
| `clear_history` | `history.clear` | history |
| `create_new_history` | `history.create` | history |
| `switch_config` | `config.switch` | config |
| `set_log_level` | `config.log_level` | config |
| `get_config` | `config.get` | config |
| `heartbeat` | `system.heartbeat` | system |
| `desktop_register` | `desktop.register` | desktop |
| `desktop_live2d_action` | `desktop.live2d_action` | desktop |
| `desktop_chat_message` | `desktop.chat_message` | desktop |
| `desktop_voice_start` | `desktop.voice_start` | desktop |
| `desktop_voice_stop` | `desktop.voice_stop` | desktop |
| `bilibili.connect` | `bilibili.connect` | bilibili |
| `bilibili.disconnect` | `bilibili.disconnect` | bilibili |
| `bilibili.update_room` | `bilibili.update_room` | bilibili |
| `minecraft.start` | `minecraft.start` | minecraft |
| `minecraft.stop` | `minecraft.stop` | minecraft |
| `translation.configure` | `translation.configure` | translation |
| `get_available_personas` | `persona.list` | persona |
| `set_persona` | `persona.set` | persona |
| `set_personality_mode` | `persona.set_mode` | persona |
| `memory_organize` | `memory.organize` | memory |
| `get_wiki_pages` | `memory.list_pages` | memory |
| `sing:process` | `sing.process` | sing |
| `sing:confirm_lyrics` | `sing.confirm_lyrics` | sing |
| `sing:cancel` | `sing.cancel` | sing |
| `sing:subtitle_sync` | `sing.subtitle_sync` | sing |
| `meme_add` | `meme.add` | meme |
| `meme:list` | `meme.list` | meme |
| `meme:review` | `meme.review` | meme |
| `meme:dataset` | `meme.dataset` | meme |
| `meme:collect` | `meme.collect` | meme |

#### 服务器→客户端事件

| 旧名称 | 新名称 | 模块 |
|--------|--------|------|
| `sentence` | `chat.sentence` | chat |
| `control` | `chat.control` | chat |
| `transcript` | `chat.transcript` | chat |
| `stop_audio` | `chat.stop_audio` | chat |
| `audio_with_expression` | `chat.audio_with_expression` | chat |
| `subtitle.translation` | `chat.subtitle_translation` | chat |
| `live2d.action` | `chat.live2d_action` | chat |
| `expression` | `chat.expression` | chat |
| `connection-established` | `system.connection_established` | system |
| `model_status` | `system.model_status` | system |
| `error` | `system.error` | system |
| `config-switched` | `config.switched` | config |
| `log_level_changed` | `config.log_level_changed` | config |
| `config_data` | `config.data` | config |
| `heartbeat-ack` | `config.heartbeat_ack` | config |
| `translation.status` | `translation.status` | translation |
| `danmaku` | `bilibili.danmaku` | bilibili |
| `danmaku.status` | `bilibili.danmaku_status` | bilibili |
| `danmaku.ai_reply` | `bilibili.danmaku_ai_reply` | bilibili |
| `minecraft.status` | `minecraft.status` | minecraft |
| `sing:progress` | `sing.progress` | sing |
| `sing:complete` | `sing.complete` | sing |
| `sing:error` | `sing.error` | sing |
| `sing:lyrics_ready` | `sing.lyrics_ready` | sing |
| `sing:subtitle_line` | `sing.subtitle_line` | sing |
| `memory.organize.progress` | `memory.organize_progress` | memory |
| `memory.organize.result` | `memory.organize_result` | memory |

### 如何添加新事件

1. 在 `config/socket-events.json` 中添加事件定义
2. 在 `frontend/src/constants/socket-events.ts` 中添加 TypeScript 类型
3. 在后端 `routes.py` 中注册事件处理器
4. 运行 `python scripts/validate-events.py` 验证一致性

---

## 相关文档

- [Socket.IO API](socket-api.md) - Socket.IO 事件详细文档（中文）
- [README.md](../../README.md) - 项目概述和架构图
- [Architecture Overview](../architecture/overview.md) - 架构概览
- [AGENTS.md](../../AGENTS.md) - 项目知识库
