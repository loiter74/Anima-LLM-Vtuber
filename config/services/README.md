# 服务配置目录

本目录包含 Anima 的所有服务配置文件，按服务类型组织。

## 目录结构

```
services/
├── asr/           # 语音识别服务
│   ├── openai.yaml
│   ├── glm.yaml
│   └── mock.yaml
├── tts/           # 语音合成服务
│   ├── openai.yaml
│   ├── glm.yaml
│   ├── edge.yaml
│   └── mock.yaml
└── agent/         # AI Agent 服务
    ├── openai.yaml
    ├── glm.yaml
    ├── ollama.yaml
    └── mock.yaml
```

## 使用方法

在 `config/config.yaml` 中通过服务名称引用：

```yaml
services:
  asr: glm      # 加载 services/asr/glm.yaml
  tts: edge     # 加载 services/tts/edge.yaml
  agent: ollama # 加载 services/agent/ollama.yaml
```

## 添加新服务

1. 在对应的服务目录下创建 YAML 文件，如 `services/tts/new-provider.yaml`
2. 在 `config.yaml` 中引用：`tts: new-provider`

## 环境变量

配置文件支持环境变量替换：

```yaml
api_key: "${OPENAI_API_KEY}"
```

也可通过环境变量覆盖配置：
- `LLM_API_KEY` - 覆盖 LLM API 密钥
- `LLM_MODEL` - 覆盖 LLM 模型
- `ASR_API_KEY` - 覆盖 ASR API 密钥
- `TTS_API_KEY` - 覆盖 TTS API 密钥