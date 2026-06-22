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

## 4. Observer Pattern（观察者模式）

### 定义
定义对象间的一对多依赖关系，状态改变时通知所有依赖者。

### 应用场景
- EventBus 事件系统
- Pipeline 和 Handler 解耦

### 优势
- 解耦发布者和订阅者
- 支持优先级
- 异常隔离
- 动态订阅

---

## 5. Pipeline Pattern（管道模式）

### 定义
将数据处理流程分解为多个步骤，数据按顺序通过。

### 应用场景
- InputPipeline: ASR → 文本清洗 → 情感提取
- OutputPipeline: 句子分割 → TTS 合成

### 优势
- 责任链
- 可中断
- 可复用
- 可扩展

---

## 6. Orchestrator Pattern（编排器模式）

### 定义
管理复杂工作流，协调多个服务的交互。

### 应用场景
- ConversationOrchestrator 编排对话流程

### 优势
- 统一管理
- 依赖注入
- 易于测试
- 职责清晰

---

## 设计模式对比

| 模式 | 目的 | 项目应用 |
|------|------|----------|
| Factory | 封装对象创建 | ASR/TTS/LLM 服务创建 |
| Strategy | 封装算法 | 情感分析器、时间轴策略 |
| Provider Registry | 自动注册 | 服务商注册 |
| Observer | 事件发布订阅 | EventBus 事件系统 |
| Pipeline | 数据处理流程 | 输入/输出管道 |
| Orchestrator | 工作流编排 | 对话流程编排 |
