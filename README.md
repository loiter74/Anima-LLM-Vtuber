# Anima-LLM-Vtuber

🤖 Anima - 可配置的 AI 虚拟伴侣/VTuber 框架

## 特性

- 🔧 **Profile 驱动配置** - 通过切换 profile 轻松更换 LLM/ASR/TTS 服务商
- 🎭 **人设系统** - 可定制的角色人设，支持独立管理
- 🔌 **插件化架构** - 使用装饰器注册新服务，无需修改核心代码
- 🌊 **流式响应** - 支持流式 LLM 对话和 TTS 输出
- 🎙️ **多模态交互** - 支持语音识别 (ASR) 和语音合成 (TTS)

## 支持的服务商

| 类型 | 支持的服务商 |
|------|-------------|
| LLM | OpenAI, GLM (智谱), Ollama, Mock |
| ASR | OpenAI Whisper, GLM ASR, Mock |
| TTS | OpenAI TTS, GLM TTS, Edge TTS, Mock |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制配置模板并编辑：

```bash
cp config/config.default.yaml config/config.yaml
```

编辑 `config/config.yaml`，设置你的服务方案和 API Key：

```yaml
# 选择服务方案
profile: "glm"  # mock / openai / glm / ollama

# 选择人设
persona: "default"  # default / neuro-vtuber

# 系统配置
system:
  host: "localhost"
  port: 12394
```

设置环境变量：

```bash
export LLM_API_KEY="your-api-key"
```

### 3. 运行

```bash
python -m anima.socketio_server
```

## 配置说明

### Profile (服务方案)

Profile 定义了 ASR/TTS/LLM 的配置，位于 `config/profiles/`：

| Profile | 说明 |
|---------|------|
| `mock` | 纯 Mock 服务，用于测试 |
| `openai` | OpenAI 全家桶 |
| `glm` | 智谱 AI 全家桶 |
| `ollama` | 本地 Ollama |

### Persona (人设)

人设定义了角色的性格和对话风格，位于 `config/personas/`：

| Persona | 说明 |
|---------|------|
| `default` | 默认助手 |
| `neuro-vtuber` | VTuber 风格人设 |

## 扩展开发

### 添加新的 LLM 服务商

1. 创建配置类：

```python
# src/anima/config/providers/llm/my_llm.py
from ..base import LLMBaseConfig
from anima.config.core.registry import ProviderRegistry

@ProviderRegistry.register_config("llm", "my_llm")
class MyLLMConfig(LLMBaseConfig):
    type: Literal["my_llm"] = "my_llm"
    api_key: str
    model: str = "my-model"
```

2. 创建服务实现：

```python
# src/anima/services/agent/implementations/my_llm_agent.py
from ..interface import AgentInterface
from anima.config.core.registry import ProviderRegistry

@ProviderRegistry.register_service("llm", "my_llm")
class MyLLMAgent(AgentInterface):
    @classmethod
    def from_config(cls, config, **kwargs):
        return cls(api_key=config.api_key, model=config.model)
```

3. 创建 Profile：

```yaml
# config/profiles/my_llm.yaml
asr:
  type: mock

tts:
  type: mock

agent:
  llm_config:
    type: my_llm
    api_key: "${LLM_API_KEY}"
    model: "my-model"
```

## 项目结构

```
Anima/
├── config/
│   ├── config.yaml          # 主配置
│   ├── config.default.yaml  # 配置模板
│   ├── profiles/            # 服务方案
│   │   ├── mock.yaml
│   │   ├── openai.yaml
│   │   ├── glm.yaml
│   │   └── ollama.yaml
│   └── personas/            # 人设配置
│       ├── default.yaml
│       └── neuro-vtuber.yaml
├── src/anima/
│   ├── config/              # 配置模块
│   │   ├── core/            # 核心配置系统
│   │   └── providers/       # 服务商配置
│   ├── services/            # 服务实现
│   │   ├── agent/           # LLM 服务
│   │   ├── asr/             # 语音识别
│   │   └── tts/             # 语音合成
│   └── socketio_server.py   # 主入口
├── frontend/                # 前端 (Next.js)
├── requirements.txt
└── README.md
```

## 许可证

MIT License