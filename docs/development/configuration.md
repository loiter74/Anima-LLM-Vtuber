# 配置系统

> YAML 配置文件、环境变量和用户设置的完整指南

---

## 目录

1. [配置架构](#配置架构)
2. [主配置文件](#主配置文件)
3. [服务配置](#服务配置)
4. [功能配置](#功能配置)
5. [环境变量](#环境变量)
6. [用户设置](#用户设置)

---

## 配置架构

### 配置层次

```
系统默认配置
        ↓
YAML 配置文件 (config/config.yaml)
        ↓
环境变量覆盖 (${VAR_NAME})
        ↓
用户设置 (.user_settings.yaml)
        ↓
运行时配置 (UserSettings)
```

### 配置文件结构

```
config/
├── config.yaml              # 主配置文件
├── system.yaml              # 系统配置
├── services/                # 服务配置目录
│   ├── agent/
│   │   ├── glm.yaml
│   │   ├── openai.yaml
│   │   └── mock.yaml
│   ├── asr/
│   │   ├── faster_whisper.yaml
│   │   ├── glm.yaml
│   │   └── mock.yaml
│   ├── tts/
│   │   ├── edge.yaml
│   │   ├── glm.yaml
│   │   └── mock.yaml
│   └── vad/
│       ├── silero.yaml
│       └── mock.yaml
├── features/                # 功能配置目录
│   └── live2d.yaml
└── personas/                # 人设配置目录
    ├── default.yaml
    └── neuro-vtuber.yaml

.user_settings.yaml          # 用户设置（不提交到 Git）
.env                         # 环境变量（不提交到 Git）
```

---

## 主配置文件

### config.yaml

```yaml
# 系统配置
system:
  host: "localhost"
  port: 12394
  log_level: "INFO"
  cors_origins:
    - "http://localhost:3000"
    - "http://127.0.0.1:3000"

# 服务配置
services:
  agent: glm          # LLM 服务
  asr: faster_whisper # ASR 服务
  tts: edge           # TTS 服务 (免费，无配额)
  vad: silero         # VAD 服务

# Live2D 配置
features:
  live2d:
    enabled: true

# 人设配置
persona: "neuro-vtuber"
```

### 加载配置

```python
# src/anima/socketio_server.py
from anima.config import AppConfig

# 加载配置
app_config = AppConfig.from_yaml("config/config.yaml")

# 访问配置
print(app_config.system.port)           # 12394
print(app_config.services.agent)        # "glm"
print(app_config.persona.name)          # "neuro-vtuber"
```

---

## 服务配置

### LLM 服务配置

**GLM (智谱 AI)**
```yaml
# config/services/agent/glm.yaml
llm_config:
  type: "glm"
  api_key: "${GLM_API_KEY}"  # 从环境变量读取
  model: "glm-4-flash"
  temperature: 0.8
  max_tokens: 2000
```

**OpenAI**
```yaml
# config/services/agent/openai.yaml
llm_config:
  type: "openai"
  api_key: "${OPENAI_API_KEY}"
  model: "gpt-4"
  temperature: 0.7
  max_tokens: 2000
```

**Mock (测试用)**
```yaml
# config/services/agent/mock.yaml
llm_config:
  type: "mock"
  model: "mock-model"
  response_delay: 1.0  # 模拟延迟（秒）
```

### ASR 服务配置

**Faster-Whisper (免费，离线)**
```yaml
# config/services/asr/faster_whisper.yaml
asr_config:
  type: "faster_whisper"
  model: "large-v3"          # 模型大小
  device: "cpu"             # cpu | cuda
  compute_type: "float16"   # float16 | int8 | float32
  download_root: null       # 模型缓存目录
```

**GLM ASR**
```yaml
# config/services/asr/glm.yaml
asr_config:
  type: "glm"
  api_key: "${GLM_API_KEY}"
  language: "zh"            # zh | en
```

### TTS 服务配置

**Edge TTS (免费，无配额)**
```yaml
# config/services/tts/edge.yaml
tts_config:
  type: "edge"
  voice: "zh-CN-XiaoxiaoNeural"  # 中文女声
  rate: "+0%"                      # 语速调整
  volume: "+0%"                    # 音量调整
```

**GLM TTS**
```yaml
# config/services/tts/glm.yaml
tts_config:
  type: "glm"
  api_key: "${GLM_API_KEY}"
  voice: "zh-cn-female"      # zh-cn-female | zh-cn-male
```

### VAD 服务配置

**Silero VAD (推荐)**
```yaml
# config/services/vad/silero.yaml
vad_config:
  type: "silero"
  model: "silero_vad"        # 模型名称

  # 检测阈值
  prob_threshold: 0.8        # 概率阈值 (0.5 - 1.0)
  db_threshold: 40           # 分贝阈值 (20 - 60)

  # 触发条件
  required_hits: 8           # 开始说话需要连续命中次数
  required_misses: 20        # 停止说话需要连续未命中次数

  # 平滑窗口
  smoothing_window: 5        # 平滑窗口大小
```

**Mock VAD (测试用)**
```yaml
# config/services/vad/mock.yaml
vad_config:
  type: "mock"
  always_detect: true        # 总是检测到语音
```

---

## 功能配置

### Live2D 配置

```yaml
# config/features/live2d.yaml
enabled: true

# 模型配置
model:
  path: "/live2d/hiyori/Hiyori.model3.json"
  scale: 0.5
  position:
    x: 0
    y: 0

# 表情映射（情感 → Live2D motion）
emotion_map:
  idle: "idle"
  listening: "listening"
  thinking: "thinking"
  speaking: "speaking"
  surprised: "surprised"
  sad: "sad"
  happy: "happy"
  neutral: "neutral"
  angry: "angry"

# 有效情感列表
valid_emotions:
  - "happy"
  - "sad"
  - "angry"
  - "surprised"
  - "neutral"
  - "thinking"

# 唇同步配置
lip_sync:
  enabled: true
  sensitivity: 1.0          # 嘴部开合灵敏度 (0.5 - 2.0)
  smoothing: 0.5            # 平滑系数 (0.0 - 1.0)
  min_threshold: 0.05       # 最小音量阈值
  max_value: 1.0            # 最大嘴部开合值
  use_mouth_form: false     # 是否控制嘴型参数

# 情感系统配置
emotion_system:
  analyzer:
    type: "llm_tag_analyzer"          # llm_tag_analyzer | keyword_analyzer
    confidence_mode: "frequency"      # first | frequency | majority

  strategy:
    type: "duration_based"            # position_based | duration_based | intensity_based
    min_duration: 1.0                 # 最小时长（秒）
    emotion_weights:
      happy: 1.2
      surprised: 1.0
      neutral: 1.0
      sad: 0.8
      angry: 0.8
```

---

## 环境变量

### 支持的环境变量

| 变量名 | 用途 | 示例 |
|--------|------|------|
| `GLM_API_KEY` | GLM API 密钥 | `xxxxxxxxxxxxx` |
| `LLM_API_KEY` | 通用 LLM API 密钥 | `yyyyyyyyyyyyy` |
| `OPENAI_API_KEY` | OpenAI API 密钥 | `sk-...` |
| `ASR_API_KEY` | ASR 服务 API 密钥 | `zzzzzzzzzzzzz` |
| `TTS_API_KEY` | TTS 服务 API 密钥 | `wwwwwwwwwwwww` |

### .env 文件

```bash
# .env (项目根目录)
GLM_API_KEY=xxxxxxxxxxxxx
OPENAI_API_KEY=sk-...
```

### 在 YAML 中使用环境变量

```yaml
# config/services/agent/glm.yaml
llm_config:
  type: "glm"
  api_key: "${GLM_API_KEY}"  # 自动从环境变量读取
```

---

## 用户设置

### .user_settings.yaml

```yaml
# .user_settings.yaml (项目根目录，不提交到 Git)
log_level: "DEBUG"  # TRACE | DEBUG | INFO | WARNING | ERROR | CRITICAL
```

### 运行时修改日志级别

```python
# src/anima/socketio_server.py
from anima.config.user_settings import UserSettings

# 加载用户设置
user_settings = UserSettings(root_dir)

# 设置日志级别
user_settings.set_log_level("DEBUG")
user_settings.save()
```

### 优先级

```
用户设置 > 环境变量 > YAML 配置 > 系统默认
```

---

## 配置验证

### 配置类定义

```python
# src/anima/config/app.py
from pydantic import BaseModel

class SystemConfig(BaseModel):
    host: str = "localhost"
    port: int = 12394
    log_level: str = "INFO"
    cors_origins: List[str] = ["http://localhost:3000"]

class AppConfig(BaseModel):
    system: SystemConfig
    services: ServiceConfig
    features: FeatureConfig
    persona: PersonaConfig

    class Config:
        validate_assignment = True  # 运行时验证
```

### 配置验证

```python
# 自动验证
app_config = AppConfig.from_yaml("config/config.yaml")

# 手动验证
try:
    app_config.services.asr = "invalid_provider"
except ValidationError as e:
    print(f"配置错误: {e}")
```

---

## 总结

### 配置系统特点

1. **层次化配置**: 默认 → YAML → 环境变量 → 用户设置
2. **类型安全**: Pydantic 自动验证
3. **环境变量**: `${VAR_NAME}` 语法自动展开
4. **热重载**: 用户设置支持运行时修改
5. **Git 友好**: 敏感信息通过环境变量，不提交到 Git

### 最佳实践

1. **API 密钥**: 始终使用环境变量，不要硬编码
2. **配置分离**: 按服务、功能、人设分离配置文件
3. **类型验证**: 使用 Pydantic 确保配置正确性
4. **用户设置**: 运行时配置（如日志级别）使用 `.user_settings.yaml`

---

**最后更新**: 2026-02-28
