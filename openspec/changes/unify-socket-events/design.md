## Context

Animetta 使用 Socket.IO 进行前后端实时通信，共有 48 个唯一事件。当前命名存在三种格式混用：
- 下划线 (snake_case): `text_input`, `set_persona` 等 20 个
- 点分隔 (dot.notation): `bilibili.connect`, `minecraft.start` 等 5 个
- 冒号分隔 (colon:notation): `sing:process`, `sing:cancel` 等 4 个

参考飞书/Lark API (`im.message.receive_v1`)、Slack (`message.channels`) 等主流平台，点分隔是业界主流。

## Goals / Non-Goals

**Goals:**
- 统一所有 Socket.IO 事件为点分隔格式 `{module}.{action}`
- 创建 JSON 配置文件作为单一真相源
- 前后端都从 JSON 读取事件名
- 更新所有相关代码和文档

**Non-Goals:**
- 不引入版本号 (v1/v2) — 当前无破坏性变更需求
- 不生成 OpenAPI 文档 — 使用 Starlette 非 FastAPI，暂不支持
- 不重构事件业务逻辑 — 仅改命名，不改行为
- 不保留向后兼容层 — 开发中代码，直接全量替换

## Decisions

### 1. 选择点分隔格式

**决定**: 使用 `{module}.{action}` 格式

**理由**:
- 业界主流：飞书、Slack、GitHub 均采用
- 可读性好：`chat.text` 优于 `chat:text` 或 `chat_text`
- IDE 友好：点分隔在代码补全和搜索中表现更好

**替代方案**:
- 冒号分隔 (`chat:text`) — Socket.IO 官方示例常用，但可读性略差
- 下划线 (`chat_text`) — Python 风格，但不适合前端

### 2. 命名规范

**决定**:
- 发送类事件（客户端→服务器）：无动词，如 `chat.text`
- 接收类事件（服务器→客户端）：结果名词，如 `chat.sentence`

**理由**:
- 参考飞书：`im.message.receive_v1`（无 send/emit）
- 更简洁：`chat.text` 优于 `chat.send_text`
- 动词冗余：emit 本身就是"发送"的意思

### 3. 模块划分

**决定**: 按功能模块划分事件命名空间

| 模块 | 事件数 | 说明 |
|------|--------|------|
| `chat` | 8 | 对话交互 |
| `history` | 4 | 历史管理 |
| `config` | 5 | 配置管理 |
| `persona` | 3 | 人格管理 |
| `memory` | 4 | 记忆系统 |
| `sing` | 9 | 音乐处理 |
| `bilibili` | 6 | 直播集成 |
| `minecraft` | 3 | 游戏集成 |
| `desktop` | 5 | 桌面客户端 |
| `translation` | 2 | 翻译功能 |
| `system` | 4 | 系统事件 |
| `meme` | 5 | 梗功能 |

### 4. 配置管理

**决定**: 纯 JSON 配置，单一真相源

**文件位置**: `config/socket-events.json`

**结构**: 事件名 + payload 类型定义

**理由**:
- 单一真相源，修改事件名只需改一处
- 前后端都能读取，不需要同步脚本
- TypeScript 可以从 JSON 生成类型

**替代方案**:
- TypeScript 常量 + JSON 同步 — 需要额外脚本
- 前后端各自定义 — 容易不一致

### 5. 集成方式

**决定**:
- 前端：构建时导入 (`import events from '@/config/socket-events.json'`)
- 后端：配置系统集成（通过 `AppConfig` 加载）

**理由**:
- 前端：Vite 原生支持 JSON 导入，最简单
- 后端：与现有配置架构一致，便于测试和 mock

### 6. 验证机制

**决定**: CI/CD 检查（Docker 构建时）

**实现**: 在 `Dockerfile` 中添加验证步骤，构建失败 = 不部署

**理由**:
- Docker 构建天然适合
- 不影响服务启动速度
- 更早发现问题

### 7. 测试策略

**决定**: 自动化测试 + 端到端测试

- 自动化测试：脚本验证 JSON 与代码中的事件名一致
- E2E 测试：Playwright 测试完整流程

### 8. 回滚方案

**决定**: 不需要回滚方案

**理由**: 开发中代码，直接修复即可

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 遗漏某个事件 | 高 | 自动化测试脚本验证 |
| 前后端事件名不匹配 | 高 | CI/CD 验证 + E2E 测试 |
| payload 类型不匹配 | 中 | TypeScript 类型检查 |
| 开发者混淆新旧格式 | 低 | 文档 + 代码示例 |

## Architecture

### 文件结构

```
config/
└── socket-events.json          # 事件名定义（单一真相源）

frontend/src/
├── constants/socket-events.ts  # 从 JSON 生成 TypeScript 类型
└── composables/useSocket.ts    # 读取 JSON 中的事件名

src/animetta/orchestration/server/
└── routes.py                   # 读取 JSON 中的事件名

scripts/
└── validate-events.py          # 验证脚本（CI/CD 用）
```

### JSON 配置结构

```json
{
  "chat": {
    "text": {
      "name": "chat.text",
      "payload": {
        "text": "string",
        "user_id?": "string",
        "from_name?": "string"
      }
    },
    "sentence": {
      "name": "chat.sentence",
      "payload": {
        "text": "string",
        "seq": "number",
        "lang": "string",
        "is_complete?": "boolean"
      }
    }
  }
}
```

### 前端集成

```typescript
// frontend/src/constants/socket-events.ts
import events from '@/config/socket-events.json'

export const Events = {
  CHAT: {
    TEXT: events.chat.text.name,
    SENTENCE: events.chat.sentence.name,
  },
  SING: {
    PROCESS: events.sing.process.name,
  }
} as const

// 使用示例
socket.emit(Events.CHAT.TEXT, { text: 'hello' })
```

### 后端集成

```python
# src/animetta/orchestration/server/routes.py
import json
from pathlib import Path

def load_event_names():
    config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "socket-events.json"
    with open(config_path) as f:
        return json.load(f)

EVENTS = load_event_names()

def register_routes(sio, ...):
    sio.on(EVENTS["chat"]["text"]["name"], handlers.on_text_input)
    sio.on(EVENTS["sing"]["process"]["name"], handlers.on_sing_process)
```

## Event Mapping

### 客户端→服务器事件（37 个）

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

### 服务器→客户端事件（27 个）

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

## Migration Plan

1. **Phase 1**: 创建 `config/socket-events.json`，定义所有 48 个事件
2. **Phase 2**: 后端修改 `routes.py`，从 JSON 读取事件名
3. **Phase 3**: 后端迁移所有 `sio.emit()` 调用
4. **Phase 4**: 前端创建事件常量，迁移所有 `socket.emit()` 和 `socket.on()` 调用
5. **Phase 5**: 编写验证脚本，集成到 Docker 构建
6. **Phase 6**: 编写测试，更新文档

## Open Questions

（无，所有决策已确认）
