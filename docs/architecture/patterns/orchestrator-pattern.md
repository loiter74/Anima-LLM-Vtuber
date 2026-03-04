# Orchestrator Pattern（编排器模式）

> 🎓 **面试重点** - 设计模式实际应用
> 
> ⚠️ **注意**：部分示例代码使用旧的组件名称，这些在 v0.6.0 (2026-03-01) 已被新架构替代。
> 请参考 [CLAUDE.md](../../../CLAUDE.md) 了解最新的架构。

---

## 6. Orchestrator Pattern（编排器模式）

### 定义

编排器模式用于**管理复杂的工作流**，协调多个服务的交互。

### 项目应用

在 Anima 中，ConversationOrchestrator 编排整个对话流程。

### 代码实现

#### 6.1 Orchestrator 实现

```python
# src/anima/services/conversation/orchestrator.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class ConversationResult:
    """对话处理结果"""
    success: bool = True
    response_text: str = ""
    audio_path: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = None

class ConversationOrchestrator:
    """
    对话编排器

    整合对话流程：ASR → Agent → TTS → EventBus
    """

    def __init__(
        self,
        asr_engine,
        tts_engine,
        agent,
        websocket_send,
        session_id=None
    ):
        # 依赖的服务
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        self.agent = agent
        self.session_id = session_id

        # 创建 EventBus 和 Pipeline
        self.event_bus = EventBus()
        self.event_router = EventRouter(self.event_bus)
        self.input_pipeline = InputPipeline()
        self.output_pipeline = OutputPipeline()

        # 设置 Pipeline 步骤
        self._setup_pipelines()

        # 注册 Handlers
        self._setup_handlers(websocket_send)

    def _setup_pipelines(self):
        """设置 Pipeline 步骤"""
        self.input_pipeline.add_step(ASRStep(self.asr_engine))
        self.input_pipeline.add_step(TextCleanStep())
        self.input_pipeline.add_step(EmotionExtractionStep())

    def _setup_handlers(self, websocket_send):
        """注册事件处理器"""
        self.event_router.register("sentence", TextHandler(websocket_send))
        self.event_router.register("audio", AudioHandler(websocket_send))
        self.event_router.register("expression", ExpressionHandler(websocket_send))

    async def process_input(self, raw_input) -> ConversationResult:
        """
        处理用户输入

        编排完整的对话流程
        """
        try:
            # 1. InputPipeline 处理
            ctx = await self.input_pipeline.process(raw_input)

            if ctx.error:
                return ConversationResult(success=False, error=ctx.error)

            # 2. Agent 对话
            response_text = ""
            async for chunk in self.agent.chat_stream(ctx.text):
                response_text += chunk

                # 3. OutputPipeline 处理（流式）
                await self.output_pipeline.process_chunk(chunk)

            return ConversationResult(
                success=True,
                response_text=response_text,
                metadata=ctx.metadata
            )

        except Exception as e:
            logger.error(f"Conversation failed: {e}")
            return ConversationResult(success=False, error=str(e))

    def start(self):
        """启动编排器"""
        self.event_router.setup()

    def stop(self):
        """停止编排器"""
        self.event_router.clear()
```

#### 6.2 使用示例

```python
# 创建编排器
orchestrator = ConversationOrchestrator(
    asr_engine=asr_engine,
    tts_engine=tts_engine,
    agent=agent,
    websocket_send=ws.send,
    session_id="user-001"
)

# 启动
orchestrator.start()

# 处理输入
result = await orchestrator.process_input(audio_data)

print(f"AI 回复: {result.response_text}")

# 停止
orchestrator.stop()
```

### 优势

1. **统一管理**：管理整个对话流程的生命周期
2. **依赖注入**：所有依赖通过构造函数注入
3. **易于测试**：可以 mock 依赖进行单元测试
4. **清晰职责**：编排器只负责编排，不负责具体逻辑

### 面试要点

**Q: 为什么需要 Orchestrator？不能直接在 Handler 里调用吗？**
> A: **关键在于职责分离和生命周期管理**：
>
> 如果在 Handler 里直接调用：
> ```python
> class TextHandler:
#     async def handle(self, event):
#         # ❌ Handler 直接调用 Agent，耦合度高
#         response = await self.agent.chat(event.data)
#         await self.send(response)
# ```
>
> 用 Orchestrator：
> ```python
> # ✅ Orchestrator 负责编排，Handler 只负责发送
# orchestrator = ConversationOrchestrator(agent, asr, tts)
# result = await orchestrator.process_input(audio)
# ```
>
> **优势**：
> 1. **职责单一**：Orchestrator 编排流程，Handler 处理事件
> 2. **生命周期**：Orchestrator 管理服务的初始化和销毁
> 3. **可测试性**：可以 mock 整个 Orchestrator
> 4. **可复用**：Orchestrator 可以在不同场景复用

---

## 总结

### 设计模式对比表

| 模式 | 目的 | 项目应用场景 | 优势 |
|------|------|--------------|------|
| **Factory** | 封装对象创建 | ASR/TTS/LLM 服务创建 | 解耦创建逻辑，配置驱动 |
| **Strategy** | 封装算法 | 情感分析器、时间轴策略 | 算法可插拔，易于 A/B 测试 |
| **Provider Registry** | 自动注册 | 服务商注册 | 零修改扩展，符合开闭原则 |
| **Observer** | 事件发布订阅 | EventBus 事件系统 | 解耦发布者和订阅者 |
| **Pipeline** | 数据处理流程 | 输入/输出管道 | 责任链，可中断，可复用 |
| **Orchestrator** | 工作流编排 | 对话流程编排 | 统一管理，生命周期控制 |

### 面试准备

**必答问题**：
1. 能画出 6 种模式的类图
2. 能说明每种模式的应用场景
3. 能对比相似模式的区别
4. 能说明模式的优缺点

### 相关文档

- [技术亮点](../overview/highlights.md) - 项目亮点总结
- [数据流设计](./data-flow.md) - 完整的数据流架构
- [事件系统](./event-system.md) - EventBus 详细实现

---

**最后更新**: 2026-02-28