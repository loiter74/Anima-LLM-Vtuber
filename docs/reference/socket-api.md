# Animetta 前端-后端接口文档

**生成时间**: 2026-06-08
**更新时间**: 2026-07-11
**协议**: Socket.IO (WebSocket)

---

## 概述

Animetta 使用 Socket.IO 进行前后端通信。所有事件都是异步的，支持回调和广播两种模式。

### ⚠️ 事件命名迁移 (v2.0)

所有产品代码必须使用 `module:action` 格式。旧格式事件名仅是兼容适配器的输入/输出选择，不是可供业务代码调用的第二套 API。

适配边界只有后端路由入口 `orchestration/server/routes.py` 和统一输出适配器 `orchestration/chat_delivery.py`。一次请求只选择 canonical 或 legacy 一种输出，禁止双发。`scripts/validate-events.py` 会拒绝适配边界外的 legacy Socket.IO 字面量。

黄金路径的命令、文本、控制、错误、字幕、表情、动作和音频事件都携带以下关联字段：

```json
{
  "message_id": "UUID",
  "conversation_id": "UUID",
  "task_id": "UUID",
  "turn_id": "与 task_id 相同的 UUID"
}
```

前端每次发送生成新的 `message_id` 与 `task_id`，在本地持久化稳定的 `conversation_id`。服务端不得以空值、短 ID 或隐式默认值替代这些字段。

**事件常量文件**: `config/socket-events.json` (后端) / `frontend/src/constants/socket-events.ts` (前端)

| 旧格式 | 新格式 | 说明 |
|--------|--------|------|
| `text_input` | `chat:text` | 发送文本 |
| `sentence` | `chat:sentence` | 接收回复 |
| `control` | `chat:control` | 对话控制 |
| `interrupt_signal` | `chat:interrupt` | 中断信号 |
| `raw_audio_data` | `chat:audio` | 音频流 |
| `mic_audio_end` | `chat:audio_end` | 录音结束 |
| `transcript` | `chat:transcript` | ASR 识别结果 |
| `stop_audio` | `chat:stop_audio` | 停止音频 |
| `audio_with_expression` | `chat:audio_with_expression` | 带表情的音频 |
| `memory_organize` | `memory:organize` | 整理记忆 |
| `get_wiki_pages` | `memory:list_pages` | 获取记忆页面 |
| `get_available_personas` | `persona:list` | 获取人格列表 |
| `set_persona` | `persona:set` | 切换人格 |
| `set_personality_mode` | `persona:set_mode` | 切换模式 |
| `switch_config` | `config:switch` | 切换配置 |
| `get_config` | `config:get` | 获取配置 |
| `set_log_level` | `config:log_level` | 设置日志级别 |
| `model_status` | `system:model_status` | 模型状态 |
| `error` | `system:error` | 错误事件 |
| `sing:process` | `sing:process` | (不变) |
| `bilibili.connect` | `bilibili:connect` | (不变) |
| `minecraft.connect` | `minecraft:connect` | 连接 mc-mcp profile |
| `minecraft.status` | `minecraft:status` | 读取 server/bot/viewer 状态 |
| `minecraft.disconnect` | `minecraft:disconnect` | 只断开 Bot |
| `minecraft.shutdown` | `minecraft:shutdown` | 关闭 mc-mcp 自有托管资源 |
| `minecraft.reattach_viewer` | `minecraft:reattach_viewer` | 请求 MC 侧重新附身 |

---

## 1. 连接事件

### `connect`
- **方向**: 客户端 → 服务器
- **触发**: 自动连接时
- **数据**: 无

### `disconnect`
- **方向**: 客户端 → 服务器
- **触发**: 断开连接时
- **数据**: 无

---

## 2. 聊天事件

### `chat:text`
- **方向**: 客户端 → 服务器
- **触发**: 用户发送文本消息
- **旧格式**: ~~`text_input`~~ [DEPRECATED]
- **数据**:
```json
{
  "text": "消息内容",
  "message_id": "8c113f5d-4eb8-43ea-a166-05a8c62cb8ea",
  "conversation_id": "17a505b8-ea4d-49c3-ac55-edf174e93ddb",
  "task_id": "2a18273f-c66d-40aa-b8f2-0e958f90ef3a",
  "turn_id": "2a18273f-c66d-40aa-b8f2-0e958f90ef3a",
  "source": "text",
  "is_inspection": false,
  "is_acceptance": false
}
```
- **响应**: 通过 `chat:sentence` 事件流式返回

### `chat:sentence`
- **方向**: 服务器 → 客户端
- **触发**: LLM 生成回复时
- **旧格式**: ~~`sentence`~~ [DEPRECATED]
- **数据**:
```json
{
  "text": "回复文本片段",
  "seq": 0
}
```
- **说明**: `seq=0` 表示开始，`text=""` 表示结束

### `chat:control`
- **方向**: 服务器 → 客户端
- **触发**: 对话状态变化
- **旧格式**: ~~`control`~~ [DEPRECATED]
- **数据**:
```json
{
  "signal": "conversation-end"
}
```

### `chat:interrupt`
- **方向**: 客户端 → 服务器
- **触发**: 用户中断 AI 回复
- **旧格式**: ~~`interrupt_signal`~~ [DEPRECATED]
- **数据**:
```json
{
  "heard_text": "已听到的文本"
}
```

---

## 3. 语音事件

### `chat:audio`
- **方向**: 客户端 → 服务器
- **触发**: 麦克风录音时（实时流）
- **旧格式**: ~~`raw_audio_data`~~ [DEPRECATED]
- **数据**:
```json
{
  "audio": [0.1, 0.2, ...]  // float32 音频数据
}
```

### `chat:audio_end`
- **方向**: 客户端 → 服务器
- **触发**: 用户停止录音
- **旧格式**: ~~`mic_audio_end`~~ [DEPRECATED]
- **数据**: 无

### `chat:transcript`
- **方向**: 服务器 → 客户端
- **触发**: ASR 识别完成
- **旧格式**: ~~`transcript`~~ [DEPRECATED]
- **数据**:
```json
{
  "text": "识别的文本",
  "is_final": true
}
```

---

## 4. 人格事件

### `persona:list`
- **方向**: 客户端 → 服务器
- **触发**: 获取可用人格列表
- **旧格式**: ~~`get_available_personas`~~ [DEPRECATED]
- **数据**: `{}`（空对象）
- **回调响应**:
```json
{
  "personas": ["default", "anime", "assistant"]
}
```

### `persona:set`
- **方向**: 客户端 → 服务器
- **触发**: 切换人格
- **旧格式**: ~~`set_persona`~~ [DEPRECATED]
- **数据**:
```json
{
  "persona_name": "anime"
}
```
- **回调响应**:
```json
{
  "error": null  // 或错误信息
}
```

### `persona:set_mode`
- **方向**: 客户端 → 服务器
- **触发**: 切换人格模式
- **旧格式**: ~~`set_personality_mode`~~ [DEPRECATED]
- **数据**:
```json
{
  "mode": "default"  // 或 "streaming"
}
```

---

## 5. 记忆事件

### `memory:organize`
- **方向**: 客户端 → 服务器
- **触发**: 手动整理记忆
- **旧格式**: ~~`memory_organize`~~ [DEPRECATED]
- **数据**: `{}`（空对象）
- **响应事件**:
  - `memory.organize.progress`: 进度更新
  - `memory.organize.result`: 完成结果

### `memory.organize.progress`
- **方向**: 服务器 → 客户端
- **数据**:
```json
{
  "text": "Running metabolism tick...",
  "progress": 30
}
```

### `memory.organize.result`
- **方向**: 服务器 → 客户端
- **数据**:
```json
{
  "status": "ok",
  "message": "Memory organized"
}
```

### `memory:list_pages`
- **方向**: 客户端 → 服务器
- **触发**: 获取记忆页面列表
- **旧格式**: ~~`get_wiki_pages`~~ [DEPRECATED]
- **数据**:
```json
{
  "session_id": "default"
}
```
- **回调响应**:
```json
{
  "pages": [
    {
      "path": "atom_id",
      "title": "页面标题",
      "content": "页面内容",
      "page_type": "entity",
      "tags": ["tag1", "tag2"],
      "updated_at": "2026-06-08T00:00:00Z"
    }
  ]
}
```

---

## 6. 音乐事件

### `sing:process`
- **方向**: 客户端 → 服务器
- **触发**: 开始音乐处理
- **数据**:
```json
{
  "url": "bilibili视频URL",
  "auto_confirm": true
}
```

### `sing:progress`
- **方向**: 服务器 → 客户端
- **触发**: 处理进度更新
- **数据**:
```json
{
  "stage": "downloading",
  "progress": 50,
  "message": "Downloading..."
}
```

### `sing:complete`
- **方向**: 服务器 → 客户端
- **触发**: 处理完成
- **数据**:
```json
{
  "audio_url": "/path/to/audio.wav",
  "subtitle_url": "/path/to/subtitle.ass",
  "tts_audio_url": "/path/to/tts.wav",
  "vocals_url": "/path/to/vocals.wav",
  "video_title": "歌曲名称",
  "duration": 180.5,
  "lyrics": [...],
  "volumes": [...]
}
```

### `sing:error`
- **方向**: 服务器 → 客户端
- **触发**: 处理出错
- **数据**:
```json
{
  "error": "错误信息"
}
```

### `sing:confirm_lyrics`
- **方向**: 客户端 → 服务器
- **触发**: 确认歌词
- **数据**:
```json
{
  "ass_content": "ASS字幕内容"
}
```

### `sing:cancel`
- **方向**: 客户端 → 服务器
- **触发**: 取消处理
- **数据**: `{}`（空对象）

---

## 7. Bilibili 直播事件

### `bilibili.connect`
- **方向**: 客户端 → 服务器
- **触发**: 连接直播间
- **数据**:
```json
{
  "room_id": 123456
}
```

### `bilibili.disconnect`
- **方向**: 客户端 → 服务器
- **触发**: 断开直播间
- **数据**: 无

### `bilibili.update_room`
- **方向**: 客户端 → 服务器
- **触发**: 更新房间号
- **数据**:
```json
{
  "room_id": 789012
}
```

---

## 8. Minecraft 事件

### `minecraft:connect`
- **方向**: 客户端 → 服务器
- **触发**: 连接 mc-mcp profile
- **数据**: `{ "request_id": "string", "profile": "string" }`

### `minecraft:disconnect`
- **方向**: 客户端 → 服务器
- **触发**: 只断开 Bot（保留托管资源）

### `minecraft:shutdown`
- **方向**: 客户端 → 服务器
- **触发**: 关闭 mc-mcp 自有托管资源

### `minecraft:reattach_viewer`
- **方向**: 客户端 → 服务器
- **触发**: 请求 MC 侧重新附身观众

### `minecraft:status`
- **方向**: 客户端 → 服务器
- **触发**: 读取 server / bot / viewer 状态
- **服务器回复**: `minecraft:status` / `minecraft:viewer_status`

---

## 9. 配置事件

### `config:switch`
- **方向**: 客户端 → 服务器
- **触发**: 切换配置文件
- **旧格式**: ~~`switch_config`~~ [DEPRECATED]
- **数据**:
```json
{
  "config_name": "config_name"
}
```

### `config:get`
- **方向**: 客户端 → 服务器
- **触发**: 获取当前配置
- **旧格式**: ~~`get_config`~~ [DEPRECATED]
- **数据**: `{}`（空对象）

### `config:log_level`
- **方向**: 客户端 → 服务器
- **触发**: 设置日志级别
- **旧格式**: ~~`set_log_level`~~ [DEPRECATED]
- **数据**:
```json
{
  "level": "DEBUG"
}
```

---

## 10. 翻译事件

### `translation.configure`
- **方向**: 客户端 → 服务器
- **触发**: 配置翻译设置
- **数据**:
```json
{
  "enabled": true,
  "target_language": "zh"
}
```

---

## 11. 模型状态事件

### `system:model_status`
- **方向**: 服务器 → 客户端
- **触发**: 模型加载状态变化
- **旧格式**: ~~`model_status`~~ [DEPRECATED]
- **数据**:
```json
{
  "model_name": "faster_whisper",
  "status": "loaded",
  "progress": 100
}
```

---

## 12. 错误事件

### `system:error`
- **方向**: 服务器 → 客户端
- **触发**: 发生错误
- **旧格式**: ~~`error`~~ [DEPRECATED]
- **数据**:
```json
{
  "type": "error",
  "message": "错误信息"
}
```

---

## 前端组件 → 事件映射

### 左侧抽屉 (LeftDrawer)

| 组件 | 按钮/开关 | 触发事件 | 旧格式 | 数据 |
|------|----------|----------|--------|------|
| QuickControls | 🔊 Voice 滑块 | 无（本地状态） | - | - |
| QuickControls | 🎤 Microphone | `chat:audio` + `chat:audio_end` | ~~`raw_audio_data` + `mic_audio_end`~~ | 音频数据 |
| QuickControls | 🧠 Auto Memory | 无（本地状态） | - | - |
| PersonaCard | - | `persona:list` | ~~`get_available_personas`~~ | - |
| SessionStats | - | 无（本地计算） | - | - |
| MemoryCards | ▶ Send | `chat:text` | ~~`text_input`~~ | 话题文本 |
| MemoryCards | ✕ Delete | 无（本地删除） | - | - |

### 右侧面板 (InteractivePanel)

| 组件 | 按钮/开关 | 触发事件 | 旧格式 | 数据 |
|------|----------|----------|--------|------|
| ChatPanel | 发送按钮 | `chat:text` | ~~`text_input`~~ | 消息文本 |
| ChatPanel | 语音按钮 | `chat:audio` + `chat:audio_end` | ~~`raw_audio_data` + `mic_audio_end`~~ | 音频数据 |
| ChatPanel | 整理记忆 | `memory:organize` | ~~`memory_organize`~~ | - |
| SettingsPanel | 切换人格 | `persona:set` | ~~`set_persona`~~ | 人格名称 |
| SettingsPanel | 切换模式 | `persona:set_mode` | ~~`set_personality_mode`~~ | 模式名称 |
| MemoryPanel | 刷新 | `memory:list_pages` | ~~`get_wiki_pages`~~ | session_id |
| PersonalityPanel | 切换人格 | `persona:set` | ~~`set_persona`~~ | 人格名称 |
| MusicCard | 开始制作 | `sing:process` | (不变) | URL |
| MusicCard | 确认歌词 | `sing:confirm_lyrics` | (不变) | ASS内容 |
| MusicCard | 取消 | `sing:cancel` | (不变) | - |

### 底部导航 (Mobile)

| 标签 | 功能 |
|------|------|
| 💬 聊天 | 切换到聊天面板 |
| 📺 直播 | 切换到直播面板 |
| 🧠 记忆 | 切换到记忆面板 |
| 🎭 人格 | 切换到人格面板 |
| 🎵 音乐 | 切换到音乐面板 |
| ⚙️ 设置 | 切换到设置面板 |

---

## 注意事项

1. **所有事件都是异步的** - 使用 `socket.emit()` 发送，`socket.on()` 接收
2. **回调模式** - 某些事件支持回调函数作为第三个参数
3. **错误处理** - 监听 `error` 事件处理全局错误
4. **重连机制** - Socket.IO 自动重连，监听 `connect` / `disconnect` 事件
5. **音频流** - `raw_audio_data` 是实时流，需要持续发送
