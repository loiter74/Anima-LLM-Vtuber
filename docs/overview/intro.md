# Anima 项目介绍

## 项目背景

**Anima** 是一个可配置的 AI 虚拟伴侣/VTuber 框架，展示了现代全栈开发的工程化实践。项目实现了：

- 🎙️ **多模态交互** - 语音识别（ASR）+ 语音合成（TTS）+ 文本对话（LLM）
- 🎭 **虚拟形象** - Live2D 3D 模型 + 情感表达 + 唇同步
- 🔌 **服务可插拔** - 支持多家服务商（OpenAI、智谱 GLM、Ollama 等）
- 🌊 **流式响应** - 实时流式 LLM 对话和 TTS 输出
- 🎯 **事件驱动** - 完整的事件驱动架构，支持优先级和异常隔离

---

## 核心特性

### 1. Profile 驱动的配置系统

通过简单的 YAML 配置即可切换 LLM/ASR/TTS 服务商：

```yaml
# config/config.yaml
services:
  asr: faster_whisper  # 一行代码切换 ASR 服务
  tts: edge            # 一行代码切换 TTS 服务
  agent: glm           # 一行代码切换 LLM 服务

persona: "neuro-vtuber"  # 一行代码切换人设
```

**价值**：无需修改代码，配置即服务。

---

### 2. 人设系统

独立的 Persona 管理，支持：
- 角色名称、描述、系统提示词
- 问候语和对话风格
- Live2D 模型配置

**价值**：一个框架，多个角色。

---

### 3. 插件化架构

使用装饰器注册新服务，无需修改核心代码：

```python
@ProviderRegistry.register_config("llm", "my_provider")
class MyProviderConfig(LLMBaseConfig):
    type: Literal["my_provider"] = "my_provider"
    api_key: str

@ProviderRegistry.register_service("llm", "my_provider")
class MyProviderAgent(LLMInterface):
    @classmethod
    def from_config(cls, config):
        return cls(api_key=config.api_key)
```

**价值**：符合开闭原则（Open-Closed Principle），对扩展开放，对修改关闭。

---

### 4. 流式响应

支持实时流式输出，用户体验流畅：

- **LLM 流式**：逐 Token 返回，边生成边显示
- **TTS 流式**：逐句合成，边合成边播放
- **WebSocket 双向**：实时音频输入 + 实时响应输出

**价值**：低延迟，高交互性。

---

### 5. Live2D 情感系统

业界领先的情感表达实现：

- **情感分析**：从 LLM 响应中提取情感标签 `[happy]`, `[sad]`, `[angry]`
- **时间轴计算**：根据音频时长和情感位置计算表情切换时间
- **唇同步**：音量包络分析（50Hz 采样）+ 嘴部参数控制（30fps 更新）
- **插件化架构**：可插拔的情感分析器和时间轴策略

**价值**：虚拟形象栩栩如生，增强沉浸感。

---

### 6. 事件驱动架构

完整的 EventBus + EventRouter 架构：

- **发布订阅**：解耦 Pipeline 和 Handlers
- **优先级**：HIGH/NORMAL/LOW 控制处理顺序
- **异常隔离**：单个 Handler 失败不影响其他
- **优先抢占**：FORCE 优先级无法被中断

**价值**：高内聚低耦合，易扩展。

---

## 技术栈

### 后端（Python）

| 层次 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI + Socket.IO | WebSocket 实时通信 |
| 异步运行时 | AsyncIO + uvicorn | 完全异步架构 |
| AI 服务 | OpenAI API, 智谱 GLM, Ollama | 多家 LLM 支持 |
| 离线服务 | Faster-Whisper, Silero VAD | 本地 ASR 和 VAD |
| 配置管理 | Pydantic + YAML | 类型安全的配置系统 |

### 前端（TypeScript）

| 层次 | 技术 | 说明 |
|------|------|------|
| 框架 | Next.js 16 + React 19 | 服务端渲染 + Hooks |
| 状态管理 | Zustand | 轻量级状态管理 |
| 实时通信 | Socket.IO Client | WebSocket 客户端 |
| Live2D 渲染 | pixi-live2d-display + PIXI.js | WebGL 虚拟形象 |

### 架构模式

| 模式 | 应用场景 |
|------|----------|
| Factory Pattern | 服务创建（ASR/TTS/LLM/VAD） |
| Strategy Pattern | 情感分析器和时间轴策略 |
| Observer Pattern | EventBus 事件系统 |
| Pipeline Pattern | 数据处理管道 |
| Orchestrator Pattern | 对话流程编排 |
| Service Container | 依赖注入和服务管理 |

---

## 项目价值

### 对于学习者

- **架构设计**：看到真实的企业级架构如何实现
- **设计模式**：6 种设计模式的实际应用案例
- **工程化**：配置管理、日志系统、错误处理
- **全栈开发**：Python 后端 + React 前端 + WebSocket 通信

### 对于面试

- **亮点突出**：事件驱动、插件化、流式响应
- **架构清晰**：Pipeline + EventBus + Orchestrator 三层架构
- **可扩展性**：如何设计可扩展的系统
- **工程实践**：类型安全、异步编程、状态管理

### 对于开发者

- **快速上手**：5 分钟运行项目
- **易于扩展**：添加新服务只需 3 步
- **配置灵活**：YAML 配置，无需改代码
- **文档完善**：架构文档、API 文档、示例代码

---

## 使用场景

1. **学习参考**：作为全栈开发和架构设计的学习项目
2. **二次开发**：基于 Anima 开发自己的 VTuber 应用
3. **面试展示**：展示工程化能力和架构设计思维
4. **生产使用**：实际部署为 AI 虚拟伴侣服务

---

## 项目特色

与同类项目相比，Anima 的独特之处：

| 特性 | Anima | 其他项目 |
|------|-------|----------|
| 架构设计 | ✅ 事件驱动 + Pipeline | ❌ 简单的 MVC |
| 可扩展性 | ✅ 插件化 + 开闭原则 | ❌ 硬编码 |
| 配置管理 | ✅ Profile 驱动 | ❌ 环境变量 |
| Live2D 集成 | ✅ 情感系统 + 唇同步 | ❌ 简单模型加载 |
| 文档质量 | ✅ 完整架构文档 | ❌ 只有 README |
| 流式响应 | ✅ LLM + TTS 双流式 | ❌ 批量处理 |

---

## 下一步

- 📖 [技术亮点详解](highlights.md) - 了解架构设计的核心价值
- 🏗️ [设计模式详解](../architecture/design-patterns.md) - 深入理解设计模式应用
- 🚀 [快速开始](../development/quickstart.md) - 5 分钟运行项目
- 💼 [简历素材](../resume/project-highlights.md) - 准备面试和简历

---

**最后更新**: 2026-02-28
