# Animetta 前端-后端接口文档

**生成时间**: 2026-06-08
**协议**: Socket.IO (WebSocket)

---

## 概述

Animetta 使用 Socket.IO 进行前后端通信。所有事件都是异步的，支持回调和广播两种模式。

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

### `text_input`
- **方向**: 客户端 → 服务器
- **触发**: 用户发送文本消息
- **数据**:
```json
{
  "text": "消息内容",
  "user_id": "user",
  "from_name": "User"
}
```
- **响应**: 通过 `sentence` 事件流式返回

### `sentence`
- **方向**: 服务器 → 客户端
- **触发**: LLM 生成回复时
- **数据**:
```json
{
  "text": "回复文本片段",
  "seq": 0
}
```
- **说明**: `seq=0` 表示开始，`text=""` 表示结束

### `control`
- **方向**: 服务器 → 客户端
- **触发**: 对话状态变化
- **数据**:
```json
{
  "signal": "conversation-end"
}
```

### `interrupt_signal`
- **方向**: 客户端 → 服务器
- **触发**: 用户中断 AI 回复
- **数据**:
```json
{
  "heard_text": "已听到的文本"
}
```

---

## 3. 语音事件

### `raw_audio_data`
- **方向**: 客户端 → 服务器
- **触发**: 麦克风录音时（实时流）
- **数据**:
```json
{
  "audio": [0.1, 0.2, ...]  // float32 音频数据
}
```

### `mic_audio_end`
- **方向**: 客户端 → 服务器
- **触发**: 用户停止录音
- **数据**: 无

### `transcript`
- **方向**: 服务器 → 客户端
- **触发**: ASR 识别完成
- **数据**:
```json
{
  "text": "识别的文本",
  "is_final": true
}
```

---

## 4. 人格事件

### `get_available_personas`
- **方向**: 客户端 → 服务器
- **触发**: 获取可用人格列表
- **数据**: `{}`（空对象）
- **回调响应**:
```json
{
  "personas": ["default", "anime", "assistant"]
}
```

### `set_persona`
- **方向**: 客户端 → 服务器
- **触发**: 切换人格
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

### `set_personality_mode`
- **方向**: 客户端 → 服务器
- **触发**: 切换人格模式
- **数据**:
```json
{
  "mode": "default"  // 或 "streaming"
}
```

---

## 5. 记忆事件

### `memory_organize`
- **方向**: 客户端 → 服务器
- **触发**: 手动整理记忆
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

### `get_wiki_pages`
- **方向**: 客户端 → 服务器
- **触发**: 获取记忆页面列表
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

### `minecraft.start`
- **方向**: 客户端 → 服务器
- **触发**: 启动 Minecraft 机器人
- **数据**: `{}`（空对象）

### `minecraft.stop`
- **方向**: 客户端 → 服务器
- **触发**: 停止 Minecraft 机器人
- **数据**: 无

---

## 9. 配置事件

### `switch_config`
- **方向**: 客户端 → 服务器
- **触发**: 切换配置文件
- **数据**:
```json
{
  "config_name": "config_name"
}
```

### `get_config`
- **方向**: 客户端 → 服务器
- **触发**: 获取当前配置
- **数据**: `{}`（空对象）

### `set_log_level`
- **方向**: 客户端 → 服务器
- **触发**: 设置日志级别
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

### `model_status`
- **方向**: 服务器 → 客户端
- **触发**: 模型加载状态变化
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

### `error`
- **方向**: 服务器 → 客户端
- **触发**: 发生错误
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

## 新增功能接口需求

### 记忆卡片功能（待实现）

| 功能 | 需要的接口 | 说明 |
|------|-----------|------|
| 获取记忆话题列表 | `get_memory_topics` | 返回结构化的话题列表 |
| 发送话题到聊天 | `text_input` | 复用现有接口 |
| 删除记忆话题 | `delete_memory_topic` | 新增接口 |
| 自动提取话题 | `extract_topics` | 新增接口（可选） |

---

## 注意事项

1. **所有事件都是异步的** - 使用 `socket.emit()` 发送，`socket.on()` 接收
2. **回调模式** - 某些事件支持回调函数作为第三个参数
3. **错误处理** - 监听 `error` 事件处理全局错误
4. **重连机制** - Socket.IO 自动重连，监听 `connect` / `disconnect` 事件
5. **音频流** - `raw_audio_data` 是实时流，需要持续发送
