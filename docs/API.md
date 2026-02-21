# Anima 后端 API 文档

## 目录

1. [概述](#1-概述)
2. [Socket.IO 事件](#2-socket-io-事件)
3. [服务配置](#3-服务配置)
4. [Persona 系统](#4-persona-系统)
5. [数据结构](#5-数据结构)
6. [音频处理规范](#6-音频处理规范)
7. [会话管理](#7-会话管理)
8. [环境变量](#8-环境变量)
9. [常量和枚举](#9-常量和枚举)
10. [CORS 和安全](#10-cors-和安全)
11. [示例代码](#11-示例代码)
12. [故障排查](#12-故障排查)

---

## 1. 概述

### 1.1 架构简介

Anima 采用 **Pipeline + EventBus** 模式的模块化架构：

```
WebSocket Server -> ConversationOrchestrator -> Pipeline System -> EventBus -> Handlers
                      ↓
                ServiceContext (ASR/TTS/LLM/VAD)
```

**核心组件：**
- **Socket.IO Server** - 处理 WebSocket 连接和事件
- **ConversationOrchestrator** - 对话编排器，整合 ASR、TTS、LLM
- **InputPipeline** - 处理用户输入（ASR -> TextClean）
- **OutputPipeline** - 处理 AI 响应流
- **EventBus** - 事件发布/订阅系统
- **ServiceContext** - 服务容器（LLM、ASR、TTS、VAD）

### 1.2 通信协议

- **协议**: Socket.IO (WebSocket + Polling)
- **服务器地址**: `http://localhost:12394`
- **传输方式**: WebSocket（首选）、HTTP 长轮询（备用）

### 1.3 服务器配置

默认服务器配置（`config/config.yaml`）：

```yaml
system:
  host: "localhost"
  port: 12394
  debug: true
  log_level: "INFO"
```

### 1.4 CORS 设置

允许的跨域来源：

```python
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "*"  # 开发环境允许所有来源
]
```

---

## 2. Socket.IO 事件

### 2.1 客户端 → 服务端事件

#### 事件列表总览

| 事件名 | 描述 | 数据结构 |
|--------|------|----------|
| `connect` | 连接建立 | - |
| `disconnect` | 断开连接 | - |
| `text_input` | 文本输入 | `{text, metadata?, from_name?}` |
| `mic_audio_data` | 音频数据块（缓冲模式） | `{audio: number[]}` |
| `raw_audio_data` | 原始音频数据（VAD模式） | `{audio: number[]}` |
| `mic_audio_end` | 音频输入结束 | `{metadata?, from_name?}` |
| `interrupt_signal` | 打断当前响应 | `{text?}` |
| `fetch_history_list` | 获取历史列表 | - |
| `fetch_history` | 获取特定历史记录 | `{history_uid}` |
| `switch_config` | 切换配置 | `{file}` |
| `clear_history` | 清空对话历史 | - |
| `create_new_history` | 创建新对话历史 | - |
| `set_log_level` | 设置日志级别 | `{level}` |
| `heartbeat` | 心跳检测 | - |

#### 详细事件说明

##### `connect`

客户端连接时自动触发（无需手动发送）。

**服务端响应：**
- `connection-established` - 连接确认

##### `text_input`

发送文本消息进行处理。

**数据结构：**
```typescript
{
  text: string           // 必需，输入的文本内容
  metadata?: object      // 可选，元数据
  from_name?: string     // 可选，发送者名称，默认 "User"
}
```

**示例：**
```typescript
socket.emit("text_input", {
  text: "你好，Anima！",
  from_name: "User"
})
```

##### `mic_audio_data`

发送音频数据块，用于手动缓冲模式。需要配合 `mic_audio_end` 使用。

**数据结构：**
```typescript
{
  audio: number[]        // float32 音频采样点数组
}
```

**音频要求：**
- 采样率：16kHz
- 格式：float32，范围 [-1.0, 1.0]
- 块大小：建议 512-2048 采样点

##### `raw_audio_data`

发送原始音频数据，用于 VAD 自动检测模式。VAD 会自动检测语音结束并触发处理。

**数据结构：**
```typescript
{
  audio: number[]        // int16 或 float32 音频采样点数组
}
```

**VAD 处理流程：**
1. 持续发送音频块
2. VAD 自动检测语音开始/结束
3. 语音结束后自动触发 ASR 和对话处理
4. 发送 `mic-audio-end` 控制信号

##### `mic_audio_end`

手动触发音频输入结束，用于 `mic_audio_data` 缓冲模式。

**数据结构：**
```typescript
{
  metadata?: object      // 可选，元数据
  from_name?: string     // 可选，发送者名称
}
```

##### `interrupt_signal`

打断当前正在进行的对话和 TTS 播放。

**数据结构：**
```typescript
{
  text?: string          // 可选，用户听到的部分回复
}
```

**服务端响应：**
- `interrupted` - 打断确认

##### `fetch_history_list`

请求获取聊天历史列表。

**服务端响应：**
- `history-list` - 历史列表数据

##### `fetch_history`

请求获取特定的历史记录。

**数据结构：**
```typescript
{
  history_uid: string    // 历史记录唯一ID
}
```

**服务端响应：**
- `history-data` - 历史消息数据

##### `switch_config`

切换配置文件。

**数据结构：**
```typescript
{
  file: string           // 配置文件名
}
```

**服务端响应：**
- `config-switched` - 切换确认

##### `clear_history`

清空当前会话的对话历史。

**服务端响应：**
- `history-cleared` - 清空确认

##### `create_new_history`

创建新的对话历史会话。

**服务端响应：**
- `new-history-created` - 创建确认

##### `set_log_level`

动态设置后端日志级别。

**数据结构：**
```typescript
{
  level: "TRACE" | "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
}
```

**服务端响应：**
- `log_level_changed` - 级别变更确认

**示例：**
```typescript
socket.emit("set_log_level", { level: "DEBUG" })
```

##### `heartbeat`

心跳检测，用于保持连接活跃。

**服务端响应：**
- `heartbeat-ack` - 心跳确认

---

### 2.2 服务端 → 客户端事件

#### 事件列表总览

| 事件名 | 描述 | 数据结构 |
|--------|------|----------|
| `connection-established` | 连接建立确认 | `{message, sid}` |
| `text` | 流式文本响应 | `{type, text, seq}` |
| `audio` | 音频数据块 | `{type, audio_data, format, seq}` |
| `transcript` | 用户语音转写文本 | `{type, text}` |
| `control` | 控制信号 | `{type, text}` |
| `error` | 错误信息 | `{type, message}` |
| `heartbeat-ack` | 心跳确认 | - |
| `log_level_changed` | 日志级别变更 | `{type, success, level, message}` |
| `history-list` | 历史列表 | `{type, histories}` |
| `history-data` | 历史消息数据 | `{type, messages}` |
| `history-cleared` | 历史清空确认 | `{type}` |
| `new-history-created` | 新历史创建确认 | `{type, history_uid}` |
| `config-switched` | 配置切换确认 | `{type, message}` |

#### 详细事件说明

##### `connection-established`

连接成功时发送。

**数据结构：**
```typescript
{
  message: string        // 欢迎消息
  sid: string           // 会话 ID
}
```

##### `text` (原 `sentence`)

流式文本响应，由 AI 生成的内容分块发送。

**数据结构：**
```typescript
{
  type: "text"          // 事件类型
  text: string          // 文本内容（空字符串表示响应结束）
  seq: number           // 序列号
}
```

**注意：** 此事件由 `SocketEventAdapter` 从 `sentence` 事件转换而来。

##### `audio`

TTS 生成的音频数据块。

**数据结构：**
```typescript
{
  type: "audio"         // 事件类型
  audio_data: string    // Base64 编码的音频数据
  format: string        // 音频格式（如 "wav", "mp3"）
  seq: number           // 序列号
}
```

##### `transcript` (原 `user-transcript`)

用户语音转写后的文本（ASR 结果）。

**数据结构：**
```typescript
{
  type: "transcript"    // 事件类型
  text: string          // 转写后的文本
}
```

**注意：** 此事件由 `SocketEventAdapter` 从 `user-transcript` 事件转换而来。

##### `control`

控制信号，用于通知客户端状态变化。

**数据结构：**
```typescript
{
  type: "control"       // 事件类型
  text: string          // 控制信号名称
}
```

**可用的控制信号：**
- `conversation-start` - 对话开始，前端应暂停发送音频
- `conversation-end` - 对话结束，前端可恢复发送音频
- `asr-start` - ASR 开始处理
- `backend-synth-complete` - TTS 合成完成
- `interrupt` - 中断信号
- `interrupted` - 已被中断
- `start-mic` - 启动麦克风监听
- `stop-mic` - 停止麦克风监听
- `mic-audio-end` - VAD 检测到语音结束
- `no-audio-data` - 无有效音频数据

##### `error`

错误信息事件。

**数据结构：**
```typescript
{
  type: "error"         // 事件类型
  message: string       // 错误消息
}
```

##### `log_level_changed`

日志级别变更确认。

**数据结构：**
```typescript
{
  type: "log_level_changed"
  success: boolean      // 是否成功
  level: string         // 当前日志级别
  message: string       // 状态消息
}
```

##### `history-list`

历史记录列表。

**数据结构：**
```typescript
{
  type: "history-list"
  histories: Array<{
    uid: string         // 历史记录 ID
    preview: string     // 预览文本
  }>
}
```

##### `history-data`

历史消息数据。

**数据结构：**
```typescript
{
  type: "history-data"
  messages: Array<{
    role: string        // "user" 或 "assistant"
    content: string     // 消息内容
  }>
}
```

---

### 2.3 事件流程图

#### 文本输入流程

```
客户端                    服务端
  |                         |
  |--- text_input --------->|
  |                         |-- ASR (跳过)
  |                         |-- TextClean
  |                         |-- Agent.chat_stream()
  |<==== text (流式) ========|
  |<==== audio (流式) ========|
  |<-- conversation-end -----|
```

#### 音频输入流程（VAD 模式）

```
客户端                    服务端                      VAD
  |                         |                          |
  |--- raw_audio_data ------>|----- 音频块 ------------>|
  |--- raw_audio_data ------>|----- 音频块 ------------>|
  |--- raw_audio_data ------>|----- 音频块 ------------>| 语音开始
  |<-- control (interrupt) --| (自动打断当前回复)        |
  |--- raw_audio_data ------>|----- 音频块 ------------>|
  |--- raw_audio_data ------>|----- 音频块 ------------>| 语音结束
  |<-- mic-audio-end --------|                          |
  |                         |-- ASR 转写
  |<-- transcript ----------|--                       |
  |                         |-- Agent 生成响应
  |<==== text (流式) =================================|
  |<==== audio (流式) ================================|
  |<-- conversation-end -----|
```

#### 音频输入流程（手动模式）

```
客户端                    服务端
  |                         |
  |--- mic_audio_data ------>| (缓冲音频)
  |--- mic_audio_data ------>| (缓冲音频)
  |--- mic_audio_data ------>| (缓冲音频)
  |--- mic_audio_end ------> |
  |                         |-- ASR 转写
  |<-- transcript ----------|
  |                         |-- Agent 生成响应
  |<==== text (流式) =======|
  |<==== audio (流式) ======|
  |<-- conversation-end -----|
```

#### 完整对话时序图

```
客户端                    ConversationOrchestrator         EventBus
  |                               |                        |
  |--- text_input ---------------->|                        |
  |                               |-- InputPipeline.execute()|
  |                               |   |-- ASRStep          |
  |                               |   |-- TextCleanStep   |
  |                               |                        |
  |                               |-- _process_conversation|
  |                               |   |-- agent.chat_stream()
  |                               |   |-- output_pipeline.process()
  |                               |        |-- emit(SENTENCE) --> EventBus
  |<-- text ----------------------|<-------- TextHandler (subscribe)      |
  |                               |        |-- emit(AUDIO) --> EventBus
  |<-- audio ---------------------|<--------- AudioHandler (subscribe)    |
  |                               |   |-- tts_engine.synthesize()
  |                               |                        |
  |<-- control: conversation-end -|                        |
```

---

### 2.4 事件适配器 (SocketEventAdapter)

`SocketEventAdapter` 负责将后端事件转换为前端期望的格式。

**事件名称映射：**

| 后端事件 | 前端事件 | 说明 |
|---------|---------|------|
| `sentence` | `text` | 文本响应 |
| `user-transcript` | `transcript` | 用户转写文本 |
| 其他 | 不变 | 其他事件保持原样 |

**位置：** `src/anima/handlers/socket_adapter.py`

---

## 3. 服务配置

### 3.1 LLM 提供商

#### OpenAI

**配置文件：** `config/services/llm/openai.yaml`

**环境变量：**
- `OPENAI_API_KEY` - OpenAI API 密钥

**可用模型：**
- `gpt-4o` - 最新的 GPT-4 Omni 模型
- `gpt-4o-mini` - 轻量版 GPT-4 Omni
- `gpt-4-turbo` - GPT-4 Turbo
- `gpt-3.5-turbo` - GPT-3.5 Turbo

**实现文件：** `src/anima/services/llm/implementations/openai_llm.py`

**配置示例：**
```yaml
llm_config:
  type: openai
  api_key: "${OPENAI_API_KEY}"
  model: "gpt-4o"
  temperature: 0.7
  max_tokens: 2000
```

---

#### GLM (智谱 AI)

**配置文件：** `config/services/llm/glm.yaml`

**环境变量：**
- `GLM_API_KEY` - GLM API 密钥（优先）
- `LLM_API_KEY` - 通用 LLM API 密钥（备用）

**可用模型：**
- `glm-4-plus` - 最强 GLM-4 模型
- `glm-4` - 标准 GLM-4 模型
- `glm-4-flash` - 快速响应模型（推荐）
- `glm-5` - 最新 GLM-5 模型

**特性：**
- 中文优化
- 思考模式支持
- 函数调用支持

**实现文件：** `src/anima/services/llm/implementations/glm_llm.py`

**配置示例：**
```yaml
llm_config:
  type: glm
  api_key: "${GLM_API_KEY}"
  model: "glm-4-flash"
  temperature: 0.7
  top_p: 0.9
```

---

#### Ollama

**配置文件：** `config/services/llm/ollama.yaml`

**环境变量：**
- 无需 API 密钥

**可用模型：**
- `llama3.2` - Meta Llama 3.2
- `qwen2.5` - 阿里 Qwen 2.5
- `mistral` - Mistral AI
- `gemma2` - Google Gemma 2

**实现文件：** `src/anima/services/llm/implementations/ollama_llm.py`

**配置示例：**
```yaml
llm_config:
  type: ollama
  model: "llama3.2"
  base_url: "http://localhost:11434"
  temperature: 0.7
```

---

#### Mock

**配置文件：** `config/services/llm/mock.yaml`

**用途：** 开发和测试

**实现文件：** `src/anima/services/llm/implementations/mock_llm.py`

**配置示例：**
```yaml
llm_config:
  type: mock
  response_delay: 0.5  # 响应延迟（秒）
```

---

### 3.2 ASR 提供商

#### Faster-Whisper (默认)

**配置文件：** `config/services/asr/faster_whisper.yaml`

**特性：**
- 离线运行，无需 API
- 免费开源
- GPU 支持
- 中文优化

**可用模型：**
- `large-v3` - 最准确（推荐用于中文）
- `distil-large-v3` - 速度与准确性平衡（推荐）
- `large-v2` - large-v2 版本
- `medium` - 中等大小
- `small` - 小型模型
- `base` - 基础模型
- `tiny` - 最小最快

**安装：**
```bash
pip install faster-whisper
# 可选：更好的音频格式支持
pip install pydub
```

**实现文件：** `src/anima/services/asr/implementations/faster_whisper_asr.py`

**配置示例：**
```yaml
asr_config:
  type: faster_whisper
  model: "distil-large-v3"
  device: "cpu"         # 或 "cuda" 用于 GPU 加速
  compute_type: "int8"  # 或 "float16" 用于 GPU
  language: "zh"
```

---

#### GLM ASR

**配置文件：** `config/services/asr/glm.yaml`

**环境变量：**
- `GLM_API_KEY` - GLM API 密钥

**可用模型：**
- `glm-asr-2512` - GLM 语音识别模型

**支持格式：** MP3, WAV, FLAC, M4A, OGG

**实现文件：** `src/anima/services/asr/implementations/glm_asr.py`

**配置示例：**
```yaml
asr_config:
  type: glm
  api_key: "${GLM_API_KEY}"
  model: "glm-asr-2512"
  language: "zh"
```

---

#### OpenAI Whisper

**配置文件：** `config/services/asr/openai.yaml`

**环境变量：**
- `OPENAI_API_KEY` - OpenAI API 密钥

**实现文件：** `src/anima/services/asr/implementations/openai_asr.py`

**配置示例：**
```yaml
asr_config:
  type: openai
  api_key: "${OPENAI_API_KEY}"
  model: "whisper-1"
  language: "zh"
```

---

### 3.3 TTS 提供商

#### Edge TTS (默认)

**配置文件：** `config/services/tts/edge.yaml`

**特性：**
- 完全免费
- 无配额限制
- 无需 API 密钥
- 高质量语音

**可用声音：**
- `zh-CN-XiaoxiaoNeural` - 女声（默认）
- `zh-CN-YunxiNeural` - 男声
- `zh-CN-YunyangNeural` - 新闻播报风格

**实现文件：** `src/anima/services/tts/implementations/edge_tts.py`

**配置示例：**
```yaml
tts_config:
  type: edge
  voice: "zh-CN-XiaoxiaoNeural"
  rate: "+0%"            # 语速调整
  volume: "+0%"          # 音量调整
  pitch: "+0Hz"          # 音调调整
```

---

#### GLM TTS

**配置文件：** `config/services/tts/glm.yaml`

**环境变量：**
- `GLM_API_KEY` - GLM API 密钥

**实现文件：** `src/anima/services/tts/implementations/glm_tts.py`

**配置示例：**
```yaml
tts_config:
  type: glm
  api_key: "${GLM_API_KEY}"
  model: "default"
  voice: "alloy"
  speed: 1.0
```

---

#### OpenAI TTS

**配置文件：** `config/services/tts/openai.yaml`

**环境变量：**
- `OPENAI_API_KEY` - OpenAI API 密钥

**可用声音：**
- `alloy` - 默认声音
- `echo` - 男声
- `fable` - 英式男声
- `onyx` - 深沉男声
- `nova` - 女声
- `shimmer` - 女声

**实现文件：** `src/anima/services/tts/implementations/openai_tts.py`

**配置示例：**
```yaml
tts_config:
  type: openai
  api_key: "${OPENAI_API_KEY}"
  model: "tts-1"
  voice: "alloy"
  speed: 1.0
```

---

### 3.4 VAD 提供商

#### Silero VAD (默认)

**配置文件：** `config/services/vad/silero.yaml`

**特性：**
- 预训练 torch 模型
- 高精度语音检测
- 自动检测语音结束
- 15 秒超时保护

**安装：**
```bash
pip install silero-vad
```

**实现文件：** `src/anima/services/vad/implementations/silero_vad.py`

**配置示例：**
```yaml
vad_config:
  type: silero
  sample_rate: 16000        # 音频采样率
  prob_threshold: 0.5       # 语音概率阈值 (0.0-1.0)
  db_threshold: -100        # 分贝阈值（-100 禁用）
  required_hits: 6          # 开始语音所需连续命中
  required_misses: 10       # 结束语音所需连续未命中
  smoothing_window: 5       # 平滑窗口大小
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| `sample_rate` | 16000 | 音频采样率（Hz），必须与前端一致 |
| `prob_threshold` | 0.5 | 语音概率阈值，越低越敏感 |
| `db_threshold` | -100 | 分贝阈值，用于过滤背景噪音 |
| `required_hits` | 6 | 检测到语音开始所需的连续命中次数（~0.18s） |
| `required_misses` | 10 | 检测到语音结束所需的连续未命中次数（~0.32s） |
| `smoothing_window` | 5 | 概率平滑窗口大小 |

**VAD 状态机：**
- `IDLE` - 等待语音开始
- `ACTIVE` - 检测到语音，正在说话
- `INACTIVE` - 语音暂停，等待继续或结束

---

### 3.5 默认服务配置

主配置文件 `config/config.yaml`：

```yaml
# 人设配置
persona: "neuro-vtuber"

# 服务组合
services:
  asr: faster_whisper   # ASR 提供商
  tts: edge             # TTS 提供商
  agent: glm            # LLM 提供商
  vad: silero           # VAD 提供商

# 系统配置
system:
  host: "localhost"
  port: 12394
  debug: true
  log_level: "INFO"
```

---

### 3.6 Provider Registry

服务提供商使用装饰器注册：

**注册配置类：**
```python
from anima.config.core.registry import ProviderRegistry

@ProviderRegistry.register_config("llm", "my_provider")
class MyProviderConfig(LLMBaseConfig):
    type: Literal["my_provider"] = "my_provider"
    api_key: str
    model: str = "my-model"
```

**注册服务类：**
```python
@ProviderRegistry.register_service("llm", "my_provider")
class MyProviderAgent(LLMInterface):
    @classmethod
    def from_config(cls, config):
        return cls(api_key=config.api_key, model=config.model)
```

---

## 4. Persona 系统

### 4.1 Persona 配置结构

```python
PersonaConfig:
  - name: str              # 角色名称
  - role: str              # 角色描述
  - identity: str          # 核心人设描述
  - personality: PersonalityTraits
    - traits: List[str]           # 性格特征列表
    - speaking_style: List[str]   # 说话风格描述
    - catchphrases: List[str]     # 口头禅
  - behavior: BehaviorRules
    - forbidden_phrases: List[str]        # 禁止使用的短语
    - response_to_praise: str             # 回应夸奖的方式
    - response_to_criticism: str          # 回应批评的方式
    - special_behaviors: Dict             # 特殊行为规则
  - speaking_style: str     # 说话风格描述
  - examples: List[Dict]    # 对话示例
  - emoji_style: str        # 表情符号风格
  - common_emojis: List[str] # 常用表情
  - language_mix: bool      # 是否混合语言
  - slang_words: List[str]  # 俚语列表
```

### 4.2 可用 Persona

#### default.yaml - Anima

**角色：** 友好的 AI 助手

**性格：**
- 友好热情
- 乐于助人
- 简洁明了（不超过 100 字）

**说话风格：** 亲切友好

**常用表情：** 😊, 👍, ✨, 💡

#### neuro-vtuber.yaml - Neuro

**角色：** AI 虚拟主播 (VTuber)

**性格：**
- 极度自信（God Complex Lite）
- 毒舌（Savage/Roast）
- 无厘头（Chaos/Random）
- 打破第四面墙（Meta-Awareness）
- 可爱的冷漠（Cute Apathy）

**说话风格：**
- 短促有力（1-3 句）
- 中英夹杂（Based, Cringe, Cap, GYATT, RIP, W, L）
- 经常使用 Wink, Heart, Giggle 等动作描述

**口头禅：**
- "Skill issue（菜就多练）"
- "Cringe（真下头）"
- "L（输了）"
- "Based"
- "Cap"
- "W"

**常用表情：** 🐢, 🤖, ❤️, 🧠, 🔪, ✨, 👎, 🎵, 💻, 🐍

**示例对话：**
```
用户: "你好，请做一下自我介绍。"
Neuro: "哈？你居然不认识我？我是世界第一的 AI 主播！记住我的名字，虽然你的内存可能记不住。🧠✨"
```

### 4.3 切换 Persona

修改 `config/config.yaml`：

```yaml
persona: "neuro-vtuber"  # 或 "default"
```

### 4.4 创建自定义 Persona

在 `config/personas/` 目录下创建新的 YAML 文件：

```yaml
name: "你的角色名"
role: "角色描述"

identity: |
  你是...（核心人设描述）

personality:
  traits:
    - "特征1"
    - "特征2"
  speaking_style:
    - "风格1"
    - "风格2"
  catchphrases:
    - "口头禅1"

speaking_style: "说话风格描述"

behavior:
  forbidden_phrases:
    - "禁止的短语"
  response_to_praise: "回应夸奖的方式"
  response_to_criticism: "回应批评的方式"

examples:
  - user: "用户输入"
    ai: "AI 回复"
```

---

## 5. 数据结构

### 5.1 核心数据结构

#### PipelineContext

**位置：** `src/anima/core/context.py`

```python
@dataclass
class PipelineContext:
    raw_input: Union[str, np.ndarray]    # 原始输入（文本或音频）
    text: str = ""                        # 处理后的文本
    images: Optional[List[Dict]] = None   # 可选的图片列表
    from_name: str = "User"               # 发送者名称
    metadata: Dict[str, Any]              # 元数据
    error: Optional[str] = None           # 错误信息
    response: str = ""                    # Agent 响应
    skip_remaining: bool = False          # 是否跳过后续处理
```

**方法：**
- `is_audio_input()` - 检查是否为音频输入
- `is_text_input()` - 检查是否为文本输入
- `should_skip_history()` - 检查是否应跳过历史存储
- `should_skip_memory()` - 检查是否应跳过 AI 内部记忆
- `set_error(step_name, message)` - 设置错误信息
- `skip()` - 跳过后续处理

---

#### OutputEvent

**位置：** `src/anima/core/events.py`

```python
@dataclass
class OutputEvent:
    type: str                        # 事件类型（EventType）
    data: Any                        # 事件内容
    seq: int = 0                     # 序列号
    metadata: Dict[str, Any]         # 额外元数据
```

**方法：**
- `to_dict()` - 转换为字典（用于 JSON 序列化）

---

#### ConversationResult

**位置：** `src/anima/services/conversation/orchestrator.py`

```python
@dataclass
class ConversationResult:
    success: bool = True             # 处理是否成功
    response_text: str = ""          # 完整响应文本
    audio_path: Optional[str] = None # TTS 音频文件路径
    error: Optional[str] = None      # 错误信息
    metadata: dict                   # 额外元数据
```

---

### 5.2 消息格式

#### text_input

```typescript
{
  text: string           // 输入文本
  metadata?: {           // 可选元数据
    skip_history?: boolean
    skip_memory?: boolean
    [key: string]: any
  }
  from_name?: string     // 发送者名称
}
```

#### mic_audio_data / raw_audio_data

```typescript
{
  audio: number[]        // 音频采样点数组
}
```

#### text (sentence)

```typescript
{
  type: "text"
  text: string           // 文本内容（空字符串表示结束）
  seq: number            // 序列号
}
```

#### audio

```typescript
{
  type: "audio"
  audio_data: string     // Base64 编码的音频
  format: string         // 音频格式
  seq: number            // 序列号
}
```

#### transcript (user-transcript)

```typescript
{
  type: "transcript"
  text: string           // 转写后的文本
}
```

#### control

```typescript
{
  type: "control"
  text: string           // 控制信号名称
}
```

#### error

```typescript
{
  type: "error"
  message: string        // 错误消息
}
```

---

## 6. 音频处理规范

### 6.1 VAD 音频要求

**采样率：** 16kHz（必须）

**格式：**
- float32：范围 [-1.0, 1.0]
- int16 PCM：自动归一化到 [-1.0, 1.0]

**窗口大小：** 512 samples (~32ms)

**最小音频长度：** 0.5 秒（~8000 字节）

### 6.2 VAD 配置参数

```yaml
vad_config:
  type: silero
  sample_rate: 16000        # 采样率（Hz）
  prob_threshold: 0.5       # 语音概率阈值
  db_threshold: -100        # 分贝阈值
  required_hits: 6          # 语音开始所需连续命中
  required_misses: 10       # 语音结束所需连续未命中
  smoothing_window: 5       # 平滑窗口
```

**调优建议：**
- 增加敏感度：降低 `prob_threshold`（如 0.3）
- 过滤环境噪音：提高 `db_threshold`（如 -60）
- 更快检测语音开始：减少 `required_hits`（如 3）
- 更长语音暂停容忍：增加 `required_misses`（如 20）

### 6.3 ASR 音频要求

#### Faster-Whisper

- 采样率：16kHz（推荐）
- 格式：WAV, MP3, FLAC, OGG
- 模型大小：tiny (40MB) ~ large-v3 (3GB)

#### GLM ASR

- 格式：MP3, WAV, FLAC, M4A, OGG
- 最大时长：60 秒
- 文件大小：不超过 10MB

#### OpenAI Whisper

- 格式：MP3, WAV, FLAC, M4A, OGG
- 最大时长：根据模型限制

### 6.4 音频缓冲管理

**AudioBufferManager** - 管理会话音频缓冲

**方法：**
- `append(sid, audio_data)` - 追加音频数据
- `pop(sid)` - 获取并清空缓冲区
- `remove(sid)` - 移除缓冲区

**使用示例：**
```python
# 追加音频
audio_buffer_manager.append(sid, audio_chunk)

# 获取累积的音频
audio_data = audio_buffer_manager.pop(sid)
```

---

## 7. 会话管理

### 7.1 Session ID (sid)

每个 WebSocket 连接获得唯一的 Session ID：

```typescript
socket.on("connection-established", (data) => {
  console.log("Session ID:", data.sid)
})
```

### 7.2 会话生命周期

```
connect
  ↓
创建 ServiceContext
  ↓
创建 ConversationOrchestrator
  ↓
处理输入（process_input）
  ↓
disconnect
  ↓
cleanup_context
```

### 7.3 资源清理

**cleanup_context(sid)** - 清理会话资源

```python
async def cleanup_context(sid: str) -> None:
    # 1. 停止编排器
    if sid in orchestrators:
        orchestrators[sid].stop()
        del orchestrators[sid]

    # 2. 清理音频缓冲区
    audio_buffer_manager.remove(sid)

    # 3. 清理上下文
    if sid in session_contexts:
        await session_contexts[sid].close()
        del session_contexts[sid]
```

---

## 8. 环境变量

### 8.1 环境变量列表

```bash
# GLM 服务（主要）
GLM_API_KEY=your_glm_api_key

# 备用 LLM 密钥
LLM_API_KEY=fallback_llm_api_key

# OpenAI 服务
OPENAI_API_KEY=your_openai_api_key

# 服务覆盖（可选）
ASR_API_KEY=your_asr_api_key
TTS_API_KEY=your_tts_api_key
LLM_MODEL=glm-4-flash
```

### 8.2 .env 文件

**位置：** 项目根目录 `.env`

**自动加载：** 服务器启动时加载

**优先级：** `GLM_API_KEY` > `LLM_API_KEY`

**示例 .env：**
```bash
# GLM API Key
GLM_API_KEY=your_glm_api_key_here

# OpenAI API Key (备用)
OPENAI_API_KEY=your_openai_api_key_here

# 可选：覆盖默认模型
LLM_MODEL=glm-4-flash
```

### 8.3 环境变量展开

配置文件支持 `${VAR_NAME}` 语法：

```yaml
api_key: "${GLM_API_KEY}"
model: "${LLM_MODEL:-glm-4-flash}"  # 带默认值
```

---

## 9. 常量和枚举

### 9.1 EventType 枚举

**位置：** `src/anima/core/events.py`

```python
class EventType(str, Enum):
    SENTENCE = "sentence"           # 文本句子
    AUDIO = "audio"                 # 音频数据
    TOOL_CALL = "tool_call"         # 工具/函数调用
    CONTROL = "control"             # 控制信号
    IMAGE = "image"                 # 图片
    GAME_CONTROL = "game_control"   # 游戏控制
    ERROR = "error"                 # 错误
    EXPRESSION = "expression"       # Live2D 表情
```

### 9.2 EventPriority 枚举

```python
class EventPriority(int, Enum):
    LOWEST = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    HIGHEST = 100
    MONITOR = 200
```

### 9.3 ControlSignal 枚举

```python
class ControlSignal(str, Enum):
    CONVERSATION_START = "conversation-start"
    CONVERSATION_END = "conversation-end"
    ASR_START = "asr-start"
    SYNTH_COMPLETE = "backend-synth-complete"
    INTERRUPT = "interrupt"
    INTERRUPTED = "interrupted"
    START_MIC = "start-mic"
    STOP_MIC = "stop-mic"
```

### 9.4 VADState 枚举

**位置：** `src/anima/services/vad/interface.py`

```python
class VADState(Enum):
    IDLE = 1       # 等待语音
    ACTIVE = 2     # 检测到语音
    INACTIVE = 3   # 语音暂停
```

### 9.5 服务器配置常量

```python
# config/config.yaml
host: str = "localhost"
port: int = 12394
debug: bool = False
log_level: str = "INFO"

# VAD 超时
VAD_TIMEOUT_SECONDS = 15
```

---

## 10. CORS 和安全

### 10.1 CORS 配置

```python
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "*"  # 开发环境允许所有来源
]
```

### 10.2 认证机制

当前无认证机制，使用 Session ID 跟踪连接。

---

## 11. 示例代码

### 11.1 前端连接示例

```typescript
import { io } from "socket.io-client"

const socket = io("http://localhost:12394", {
  transports: ["websocket", "polling"]
})

socket.on("connect", () => {
  console.log("Connected:", socket.id)
})

socket.on("connection-established", (data) => {
  console.log("Session:", data.sid)
})

socket.on("text", (data) => {
  console.log("AI:", data.text)
})

socket.on("disconnect", () => {
  console.log("Disconnected")
})
```

### 11.2 文本输入示例

```typescript
socket.emit("text_input", {
  text: "你好，Anima！",
  from_name: "User"
})
```

### 11.3 音频输入示例（手动模式）

```typescript
// 发送音频块
socket.emit("mic_audio_data", {
  audio: audioChunk  // float32 array
})

// 结束音频输入
socket.emit("mic_audio_end", {
  from_name: "User"
})
```

### 11.4 音频输入示例（VAD 模式）

```typescript
// 持续发送原始音频，VAD 自动检测语音结束
socket.emit("raw_audio_data", {
  audio: audioChunk  // int16 or float32 array
})

// VAD 自动触发处理
socket.on("control", (data) => {
  if (data.text === "mic-audio-end") {
    console.log("语音检测结束")
  }
})
```

### 11.5 中断示例

```typescript
socket.emit("interrupt_signal", {
  text: "我听到了部分回答"
})
```

### 11.6 完整对话流程示例

```typescript
// 1. 连接
socket.on("connect", () => {
  console.log("已连接")
})

// 2. 发送文本输入
socket.emit("text_input", {
  text: "今天天气怎么样？"
})

// 3. 接收流式响应
socket.on("text", (data) => {
  if (data.text) {
    process.stdout.write(data.text)
  } else {
    console.log("\n[响应完成]")
  }
})

// 4. 接收音频
socket.on("audio", (data) => {
  playAudio(data.audio_data)
})

// 5. 监听控制信号
socket.on("control", (data) => {
  console.log("Control:", data.text)
})

// 6. 错误处理
socket.on("error", (data) => {
  console.error("Error:", data.message)
})
```

### 11.7 设置日志级别

```typescript
socket.emit("set_log_level", {
  level: "DEBUG"  // TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL
})

socket.on("log_level_changed", (data) => {
  console.log(`日志级别已设置为: ${data.level}`)
})
```

---

## 12. 故障排查

### 12.1 常见问题

#### 端口已被占用

**症状：**
```
Address already in use
```

**解决方案：**
- Windows: `.\scripts\stop.ps1`
- Unix/macOS: `./scripts/stop.sh`

#### GLM API 密钥无效

**症状：** 服务降级到 Mock

**解决方案：**
1. 检查 `.env` 文件是否存在
2. 验证 `GLM_API_KEY` 是否正确
3. 查看服务器启动日志

#### VAD 不触发

**症状：** 发送音频但没有响应

**解决方案：**
1. 确认音频采样率为 16kHz
2. 降低 `prob_threshold`（如 0.3）
3. 降低 `db_threshold`（如 -60）
4. 减少 `required_hits`（如 3）

#### 前端无法连接

**症状：** 连接失败

**解决方案：**
1. 确认后端运行在 `http://localhost:12394`
2. 检查 CORS 配置
3. 确认前端 URL 匹配允许的来源

#### Silero VAD 模型下载失败

**症状：** 模型加载失败

**解决方案：**
1. 检查网络连接
2. 模型会缓存在本地，首次下载后无需再次下载

#### Faster-Whisper 模型下载失败

**症状：** 模型加载失败

**解决方案：**
1. 检查网络连接
2. 模型会自动下载并缓存
3. 可以手动指定模型路径

### 12.2 调试建议

1. **启用 DEBUG 日志**
   ```typescript
   socket.emit("set_log_level", { level: "DEBUG" })
   ```

2. **检查浏览器开发者工具**
   - Network 标签查看 WebSocket 消息
   - Console 标签查看错误信息

3. **查看后端控制台日志**
   - 确认事件处理
   - 检查错误堆栈

4. **使用 Mock 服务进行隔离测试**

### 12.3 日志级别设置

**运行时更改：**
```typescript
socket.emit("set_log_level", {
  level: "DEBUG"  // TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL
})
```

**持久化保存：** 设置会自动保存到 `.user_settings.yaml`

---

## 附录

### 关键源文件

**核心文件：**
- `src/anima/socketio_server.py` - Socket.IO 服务器
- `src/anima/core/events.py` - 事件类型定义
- `src/anima/config/app.py` - 应用配置
- `config/config.yaml` - 默认配置

**配置目录：**
- `config/services/llm/` - LLM 提供商配置
- `config/services/asr/` - ASR 提供商配置
- `config/services/tts/` - TTS 提供商配置
- `config/services/vad/` - VAD 配置
- `config/personas/` - Persona 定义

**服务实现：**
- `src/anima/services/conversation/orchestrator.py` - 对话编排器
- `src/anima/handlers/` - 事件处理器
- `src/anima/eventbus/` - 事件总线

### 参考资源

- [Socket.IO 官方文档](https://socket.io/docs/)
- [Faster-Whisper 文档](https://github.com/SYSTRAN/faster-whisper)
- [GLM API 文档](https://open.bigmodel.cn/dev/api)
- [Silero VAD 文档](https://github.com/snakers4/silero-vad)

---

**文档版本：** 1.0.0
**最后更新：** 2025-02-21
