# 设计模式详解

> 🎓 **面试重点** - Anima 项目中的 6 种核心设计模式

---

## 模式列表

1. [Factory Pattern（工厂模式）](./patterns/factory-pattern.md) - 封装对象创建逻辑
2. [Strategy Pattern（策略模式）](./patterns/strategy-pattern.md) - 算法可互换
3. [Provider Registry Pattern（提供者注册模式）](./patterns/provider-registry-pattern.md) - 装饰器注册
4. [Observer Pattern（观察者模式）](./patterns/observer-pattern.md) - 事件驱动
5. [Pipeline Pattern（管道模式）](./patterns/pipeline-pattern.md) - 数据处理流
6. [Orchestrator Pattern（编排器模式）](./patterns/orchestrator-pattern.md) - 流程编排

---

## 快速导航

| 模式 | 应用场景 | 核心文件 |
|------|----------|----------|
| Factory | 创建 ASR/TTS/LLM 服务 | `src/anima/services/*/factory.py` |
| Strategy | 时间轴计算策略 | `src/anima/avatar/strategies/` |
| Provider Registry | 服务商注册 | `src/anima/config/core/registry.py` |
| Observer | 事件总线 | `src/anima/events/core/bus.py` |
| Pipeline | 输入/输出处理 | `src/anima/pipeline/` |
| Orchestrator | 对话编排 | `src/anima/services/conversation/orchestrator.py` |

---

## 面试准备

**高频问题**：
- Q: 为什么用工厂模式？
- Q: EventBus 和 MessageQueue 的区别？
- Q: Pipeline 和 Chain of Responsibility 的区别？
- Q: Provider Registry 如何实现类型安全？

详细答案请查看各模式的文档。
