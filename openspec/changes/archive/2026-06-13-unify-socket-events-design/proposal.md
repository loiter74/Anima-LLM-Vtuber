# Socket.IO 事件命名统一设计文档

**日期**: 2026-06-13  
**状态**: 已批准  
**作者**: Sisyphus

---

## 1. 问题陈述

Animetta 的 Socket.IO 事件命名存在三种格式混用：
- **下划线** (snake_case): `text_input`, `set_persona` 等 20 个
- **点分隔** (dot.notation): `bilibili.connect`, `minecraft.start` 等 5 个
- **冒号分隔** (colon:notation): `sing:process`, `sing:cancel` 等 4 个

总计 48 个唯一事件，分布在 15+ 个前端文件中。

**影响**:
- 开发者记忆负担重
- 新事件不知道用哪种格式
- 无法从事件名推断模块归属

---

## 2. 设计决策

### 2.1 命名规范

**格式**: 点分隔 `{module}.{action}`

**规则**:
- 发送类事件（客户端→服务器）：无动词，如 `chat.text`
- 接收类事件（服务器→客户端）：结果名词，如 `chat.sentence`

**参考**: 飞书/Lark API (`im.message.receive_v1`)、Slack (`message.channels`)

### 2.2 配置管理

**方案**: 纯 JSON 配置，单一真相源

**文件位置**: `config/socket-events.json`

**结构**: 事件名 + payload 类型定义

### 2.3 集成方式

| 端 | 方式 | 说明 |
|----|------|------|
| **前端** | 构建时导入 | `import events from '@/config/socket-events.json'` |
| **后端** | 配置系统集成 | 通过 `AppConfig` 加载 |

### 2.4 验证机制

**方案**: CI/CD 检查（Docker 构建时）

**实现**: 在 `Dockerfile` 中添加验证步骤，构建失败 = 不部署

### 2.5 测试策略

**方案**: 自动化测试 + 端到端测试

- 自动化测试：脚本验证 JSON 与代码中的事件名一致
- E2E 测试：Playwright 测试完整流程

### 2.6 回滚方案

**方案**: 不需要回滚方案

**理由**: 开发中代码，直接修复即可

---

## 3. 架构设计

### 3.1 文件结构

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

### 3.2 JSON 配置结构

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
  },
  "sing": {
    "process": {
      "name": "sing.process",
      "payload": {
        "url?": "string",
        "file?": "string",
        "auto_confirm?": "boolean"
      }
    }
  }
}
```

### 3.3 前端集成

```typescript
// frontend/src/constants/socket-events.ts
import events from '@/config/socket-events.json'

export const Events = {
  CHAT: {
    TEXT: events.chat.text.name,
    SENTENCE: events.chat.sentence.name,
    // ...
  },
  SING: {
    PROCESS: events.sing.process.name,
    // ...
  }
} as const

// 使用示例
socket.emit(Events.CHAT.TEXT, { text: 'hello' })
```

### 3.4 后端集成

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
    # ...
```

---

## 4. 事件命名映射表

### 4.1 客户端→服务器事件（24 个）

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

### 4.2 服务器→客户端事件（23 个）

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

---

## 5. 实现步骤

### 5.1 事件常量定义

1. 创建 `config/socket-events.json`，定义所有 48 个事件
2. 创建 `frontend/src/constants/socket-events.ts`，从 JSON 生成 TypeScript 类型
3. 创建 `scripts/validate-events.py`，验证 JSON 与代码一致

### 5.2 后端迁移

1. 修改 `routes.py`，从 JSON 读取事件名
2. 修改所有 `sio.emit()` 调用，使用新事件名
3. 验证所有事件注册成功

### 5.3 前端迁移

1. 在所有 composable/stores 中导入事件常量
2. 替换所有 `socket.emit()` 和 `socket.on()` 调用
3. 验证所有事件监听注册成功

### 5.4 测试验证

1. 编写自动化测试脚本
2. 运行 E2E 测试（Playwright）
3. 验证所有功能正常

### 5.5 文档更新

1. 更新 `BACKEND_API_DOCUMENTATION.md`
2. 更新 `API_DOCUMENTATION.md`
3. 更新 `README.md`

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 遗漏某个事件 | 高 | 自动化测试脚本验证 |
| 前后端事件名不匹配 | 高 | CI/CD 验证 + E2E 测试 |
| payload 类型不匹配 | 中 | TypeScript 类型检查 |
| 开发者混淆新旧格式 | 低 | 文档 + 代码示例 |

---

## 7. 验收标准

- [ ] 所有 48 个事件使用点分隔格式
- [ ] JSON 配置文件包含所有事件定义
- [ ] 前后端都从 JSON 读取事件名
- [ ] CI/CD 验证脚本通过
- [ ] E2E 测试通过
- [ ] 文档更新完成

---

## 8. 相关文档

- [proposal.md](../2026-06-20-unify-socket-events/proposal.md)
- [design.md](../2026-06-20-unify-socket-events/design.md)
- [tasks.md](../2026-06-20-unify-socket-events/tasks.md)
- [Backend API documentation](../../../../reference/backend-api.md)
