# 设计模式

Anima 项目中应用的设计模式。

## 1. Factory Pattern（工厂模式）

### 定义
封装对象创建逻辑，客户端通过工厂类获取对象。

### 应用场景
- ASR/TTS/LLM/VAD 服务创建
- 配置驱动的服务商切换

### 优势
- 解耦创建逻辑
- 配置驱动
- 易于扩展
- 类型安全

---

## 2. Strategy Pattern（策略模式）

### 定义
封装算法族，使它们可以互相替换。

### 应用场景
- 情感分析器（关键词/LLM）
- 时间轴策略
- TTS 调度策略

### 优势
- 算法可插拔
- 易于 A/B 测试
- 符合开闭原则

---

## 3. Provider Registry Pattern（提供商注册模式）

### 定义
使用装饰器自动注册服务提供商。

### 应用场景
- LLM/ASR/TTS/VAD 服务商注册
- 零修改扩展

### 优势
- 自动注册
- 零修改扩展
- 符合开闭原则

---

## 4. State Graph Orchestration（状态图编排）

### 定义
以 LangGraph 状态图作为唯一编排方式，节点按状态转换串联数据处理流程。

### 应用场景
- `orchestration/graph/builder.py` 构建对话状态图：ASR → LLM → 情感/幽默 → TTS → 输出
- 节点保持轻量，业务逻辑下沉到 `services/` 或对应领域模块
- 通过 checkpointer 实现会话恢复与中断处理

### 优势
- 统一编排入口，取代早期 EventBus / Pipeline / Orchestrator 方案（见 ADR-001）
- 状态可检查点、可恢复
- 节点职责清晰、易于测试

---

## 设计模式对比

| 模式 | 目的 | 项目应用 |
|------|------|----------|
| Factory | 封装对象创建 | ASR/TTS/LLM 服务创建 |
| Strategy | 封装算法 | 情感分析器、时间轴策略 |
| Provider Registry | 自动注册 | 服务商注册 |
| State Graph | 状态驱动编排 | LangGraph 对话状态图 |
