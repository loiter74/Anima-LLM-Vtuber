# 服务配置方案（Profiles）

此目录包含各种服务提供者预配置方案，与 `personas/` 分离。

## 概念说明

| 目录 | 用途 | 内容 |
|------|------|------|
| `profiles/` | 服务配置 | LLM/ASR/TTS 提供者配置 |
| `personas/` | 人设配置 | 角色性格、说话风格、提示词 |

## 使用方法

在 `config.yaml` 中引用：

```yaml
profile: "glm"      # 服务配置方案
persona: "default"  # 人设配置
```

## 方案列表

| 文件 | LLM | ASR | TTS | 说明 |
|------|-----|-----|-----|------|
| `mock.yaml` | Mock | Mock | Mock | 测试用，无需 API |
| `openai.yaml` | OpenAI | Mock | Mock | OpenAI LLM |
| `glm.yaml` | GLM | GLM | GLM | 智谱 AI 全套服务 |
| `ollama.yaml` | Ollama | Mock | Mock | 本地 Ollama |
| `full-openai.yaml` | OpenAI | OpenAI | OpenAI | OpenAI 全套服务 |

## 配置覆盖优先级

1. 环境变量（最高）
2. `config.yaml` 中的配置
3. `profiles/{profile}.yaml`（基础）

## 敏感信息

请使用环境变量存储 API Key：

```yaml
agent:
  llm_config:
    api_key: "${LLM_API_KEY}"
```

然后设置环境变量：

```bash
export LLM_API_KEY="your-api-key"