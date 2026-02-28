# 事件系统

> 🎓 **面试高频考点** - EventBus 的完整实现和设计思考

---

## 目录

1. [系统概述](#系统概述)
2. [核心组件](#核心组件)
3. [优先级队列](#优先级队列)
4. [异常隔离](#异常隔离)
5. [完整实现](#完整实现)
6. [面试问答](#面试问答)

---

## 系统概述

### 设计目标

EventBus 是 Anima 的**事件驱动核心**，实现以下目标：

1. **解耦**：Pipeline（数据处理）和 Handlers（事件处理）完全解耦
2. **优先级**：支持事件优先级，关键事件优先处理
3. **异常隔离**：单个 Handler 失败不影响其他 Handler
4. **动态订阅**：运行时注册/取消订阅

### 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    EventBus Core                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │  _subscriptions: Dict[event_type, []Subscription]│  │
│  └───────────────────────────────────────────────────┘  │
│                  ↑                    ↓                  │
│            subscribe()            emit()              │
│                  ↓                    ↑                  │
│  ┌───────────────────────────────────────────────────┐  │
│  │              EventRouter Layer                    │  │
│  │  - register(event_type, handler)                 │  │
│  │  - setup() / clear()                             │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                    Handlers Layer                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │TextHandler  │  │AudioHandler │  │Live2DHandler│     │
│  │ Priority:   │  │ Priority:   │  │ Priority:   │     │
│  │ HIGH        │  │ NORMAL      │  │ NORMAL      │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
```

---

## 核心组件

### 1. EventBus（事件总线）

**职责**：
- 管理订阅关系
- 发布事件
- 通知订阅者

### 2. EventRouter（事件路由器）

**职责**：
- 注册 Handler 到 EventBus
- 管理路由生命周期
- 提供 `setup()` / `clear()` 方法

### 3. Handler（处理器）

**职责**：
- 处理具体的事件类型
- 发送数据到前端（WebSocket）

---

## 优先级队列

### 优先级定义

```python
class EventPriority(Enum):
    """事件优先级"""
    HIGH = 1      # 最高优先级（文本事件）
    NORMAL = 2    # 普通优先级（音频事件）
    LOW = 3       # 最低优先级（日志事件）
```

### 优先级使用场景

| 事件类型 | 优先级 | 原因 |
|----------|--------|------|
| **sentence** | HIGH | 文本需要立即显示，用户体验优先 |
| **audio** | NORMAL | 音频稍后播放不影响体验 |
| **expression** | NORMAL | 表情切换可以稍后 |
| **log** | LOW | 日志记录后台处理，不阻塞 |

### 排序机制

```python
def subscribe(self, event_type: str, handler: Callable, priority: EventPriority):
    """订阅事件（自动按优先级排序）"""
    subscription = Subscription(event_type, handler, priority)

    if event_type not in self._subscriptions:
        self._subscriptions[event_type] = []

    self._subscriptions[event_type].append(subscription)

    # 🔑 关键：按优先级排序（数字越小优先级越高）
    self._subscriptions[event_type].sort(
        key=lambda sub: sub.priority.value
    )

    return subscription
```

### 数据结构

```python
# 订阅表结构
_subscriptions = {
    "sentence": [
        Subscription(event_type="sentence", handler=TextHandler, priority=HIGH),
        Subscription(event_type="sentence", handler=LogHandler, priority=LOW),
    ],
    "audio": [
        Subscription(event_type="audio", handler=AudioHandler, priority=NORMAL),
        Subscription(event_type="audio", handler=LogHandler, priority=LOW),
    ]
}
```

---

## 异常隔离

### 问题场景

如果不隔离异常：

```python
# ❌ 问题场景
async def emit(self, event):
    for handler in self.handlers:
        await handler.handle(event)
        # 如果 handler 2 抛异常，handler 3 不会执行
```

### 解决方案

```python
# ✅ 异常隔离
async def emit(self, event):
    tasks = []
    for handler in self.handlers:
        # 每个包装成独立的 task
        task = self._safe_handle(handler, event)
        tasks.append(task)

    # 并发执行，异常不传播
    await asyncio.gather(*tasks, return_exceptions=True)

async def _safe_handle(self, handler, event):
    """安全调用 Handler（异常隔离）"""
    try:
        await handler.handle(event)
    except Exception as e:
        logger.error(f"Handler failed: {e}")
        # 不中断其他 Handler
```

### 价值

1. **健壮性**：单个 Handler 失败不影响其他
2. **可维护性**：不需要每个 Handler 都处理异常
3. **调试友好**：日志记录失败信息，不中断流程

---

## 完整实现

### 1. 数据结构

```python
# src/anima/core/events.py
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict

class EventType(str, Enum):
    """事件类型"""
    SENTENCE = "sentence"           # 文本句子
    AUDIO = "audio"                  # 音频数据
    AUDIO_WITH_EXPRESSION = "audio_with_expression"  # 音频+表情
    EXPRESSION = "expression"        # Live2D 表情
    CONTROL = "control"              # 控制信号
    ERROR = "error"                  # 错误事件

class EventPriority(Enum):
    """事件优先级"""
    HIGH = 1      # 最高优先级
    NORMAL = 2    # 普通优先级
    LOW = 3       # 最低优先级

@dataclass
class OutputEvent:
    """输出事件"""
    type: str          # 事件类型
    data: Any          # 事件数据
    seq: int           # 序号
    metadata: Dict = None  # 元数据
```

### 2. EventBus 实现

```python
# src/anima/eventbus/bus.py
from typing import Dict, List, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
import asyncio
from loguru import logger

@dataclass
class Subscription:
    """订阅信息"""
    event_type: str
    handler: 'BaseHandler'
    priority: EventPriority

class EventBus:
    """事件总线（观察者模式的 Subject）"""

    def __init__(self):
        # 订阅表: {event_type: [Subscription]}
        self._subscriptions: Dict[str, List[Subscription]] = {}

    def subscribe(
        self,
        event_type: str,
        handler: 'BaseHandler',
        priority: EventPriority = EventPriority.NORMAL
    ) -> Subscription:
        """
        订阅事件（注册观察者）

        Args:
            event_type: 事件类型
            handler: 处理器
            priority: 优先级

        Returns:
            订阅对象（用于取消订阅）
        """
        subscription = Subscription(event_type, handler, priority)

        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []

        self._subscriptions[event_type].append(subscription)

        # 🔑 关键：按优先级排序
        self._subscriptions[event_type].sort(
            key=lambda sub: sub.priority.value
        )

        logger.debug(f"[EventBus] Subscribed to {event_type} with priority {priority}")
        return subscription

    def unsubscribe(self, subscription: Subscription):
        """取消订阅"""
        event_type = subscription.event_type

        if event_type in self._subscriptions:
            try:
                self._subscriptions[event_type].remove(subscription)
                logger.debug(f"[EventBus] Unsubscribed from {event_type}")
            except ValueError:
                logger.warning(f"[EventBus] Subscription not found: {event_type}")

    async def emit(self, event: OutputEvent):
        """
        发布事件（通知所有观察者）

        Args:
            event: 事件对象
        """
        event_type = event.type

        if event_type not in self._subscriptions:
            logger.debug(f"[EventBus] No subscribers for {event_type}")
            return

        # 获取所有订阅者
        subscriptions = self._subscriptions[event_type]

        logger.debug(f"[EventBus] Emitting {event_type} to {len(subscriptions)} subscribers")

        # 并发调用所有 Handler（异常隔离）
        tasks = []
        for subscription in subscriptions:
            task = self._safe_handle(subscription.handler, event)
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_handle(self, handler: 'BaseHandler', event: OutputEvent):
        """
        安全调用 Handler（异常隔离）

        单个 Handler 失败不影响其他
        """
        try:
            await handler.handle(event)
        except Exception as e:
            logger.error(f"[EventBus] Handler failed: {e}", exc_info=True)
            # 不中断其他 Handler

    def clear(self):
        """清空所有订阅"""
        self._subscriptions.clear()
        logger.info("[EventBus] All subscriptions cleared")
```

### 3. EventRouter 实现

```python
# src/anima/eventbus/router.py
from typing import Dict, List, TYPE_CHECKING
from .bus import EventBus, EventPriority

if TYPE_CHECKING:
    from anima.handlers import BaseHandler

class EventRouter:
    """事件路由器"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._handlers: List['BaseHandler'] = []

    def register(
        self,
        event_type: str,
        handler: 'BaseHandler',
        priority: EventPriority = EventPriority.NORMAL
    ):
        """
        注册 Handler 到 EventBus

        Args:
            event_type: 事件类型
            handler: 处理器
            priority: 优先级

        Returns:
            self（链式调用）
        """
        # 订阅事件
        subscription = self.event_bus.subscribe(
            event_type,
            handler,
            priority
        )

        # 保存 Handler 引用（用于清理）
        self._handlers.append(handler)

        logger.info(f"[EventRouter] Registered handler for {event_type}")
        return self

    def setup(self):
        """设置路由（注册所有 Handlers）"""
        logger.info(f"[EventRouter] Setting up {len(self._handlers)} handlers")

    def clear(self):
        """清理路由"""
        for handler in self._handlers:
            # 取消所有订阅
            #（实际实现中，Handler 需要记录自己的 subscriptions）
            pass

        self._handlers.clear()
        self.event_bus.clear()
        logger.info("[EventRouter] All handlers cleared")
```

### 4. Handler 实现

```python
# src/anima/handlers/text_handler.py
from .base_handler import BaseHandler
from ..core.events import OutputEvent

class TextHandler(BaseHandler):
    """文本事件处理器"""

    def __init__(self, websocket_send):
        self.send = websocket_send

    async def handle(self, event: OutputEvent):
        """处理文本事件"""
        await self.send({
            "type": "text",
            "text": event.data,
            "seq": event.seq
        })
        logger.debug(f"[TextHandler] Sent text: {event.data[:20]}...")
```

### 5. 使用示例

```python
# 在 ConversationOrchestrator 中使用
from anima.eventbus import EventBus, EventRouter, EventPriority
from anima.handlers import TextHandler, AudioHandler

class ConversationOrchestrator:
    def __init__(self, websocket_send):
        # 创建 EventBus
        self.event_bus = EventBus()

        # 创建 EventRouter
        self.event_router = EventRouter(self.event_bus)

        # 注册 Handlers（支持优先级）
        self.event_router.register("sentence", TextHandler(websocket_send), EventPriority.HIGH)
        self.event_router.register("audio", AudioHandler(websocket_send), EventPriority.NORMAL)

    async def process_input(self, text: str):
        # 处理输入...

        # 发布事件
        await self.event_bus.emit(OutputEvent(
            type="sentence",
            data="你好！",
            seq=1
        ))

        # TextHandler 会收到事件并发送到前端
```

---

## 设计思考

### Q1: 为什么用观察者模式？

**A**: 因为需要**解耦 Pipeline 和 Handlers**。

**传统方式**：
```python
# ❌ Pipeline 直接调用 Handler
class OutputPipeline:
    async def process(self, chunks):
        async for chunk in chunks:
            await text_handler.send(chunk)    # 直接依赖
            await audio_handler.send(chunk)    # 直接依赖
            await live2d_handler.send(chunk)  # 直接依赖
```

**问题**：
- Pipeline 和 Handler 紧耦合
- 新增 Handler 需要修改 Pipeline
- 无法动态注册/取消

**观察者模式**：
```python
# ✅ Pipeline 发布事件，Handler 订阅事件
class OutputPipeline:
    async def process(self, chunks):
        async for chunk in chunks:
            await event_bus.emit(OutputEvent("sentence", chunk))

# Handler 独立订阅
event_bus.subscribe("sentence", TextHandler())
event_bus.subscribe("sentence", AudioHandler())
```

**优势**：
- Pipeline 不知道有多少 Handler
- Handler 不知道 Pipeline 的实现
- 新增 Handler 只需订阅，不需要修改 Pipeline

### Q2: 为什么需要优先级？

**A**: 因为**用户体验优先**。

**场景**：LLM 返回了一句话"你好，世界！"

**无优先级**：
```python
# ❌ 处理顺序不确定
Handler 1: LogHandler (记录日志)
Handler 2: TextHandler (发送文本)
Handler 3: AudioHandler (合成音频)

# 如果 LogHandler 先执行，可能会延迟 TextHandler
```

**有优先级**：
```python
# ✅ 文本优先处理
Handler 1: TextHandler (HIGH)    # 立即显示文本
Handler 2: AudioHandler (NORMAL) # 后台合成音频
Handler 3: LogHandler (LOW)      # 最后记录日志
```

**价值**：
- 用户在 **200ms** 内看到回复（首字延迟）
- 音频在后台合成，不阻塞文本显示
- 日志记录不影响用户体验

### Q3: 为什么需要异常隔离？

**A**: 因为**单个失败不应影响整体**。

**场景**：3 个 Handler 订阅了 `sentence` 事件

**无异常隔离**：
```python
# ❌ Handler 2 失败导致 Handler 3 不执行
Handler 1: TextHandler - 成功 ✅
Handler 2: Live2DHandler - 失败 ❌ (抛异常)
Handler 3: AudioHandler - 不执行 ⚠️ (因为前面的异常)

# 结果：用户看不到文本，也听不到音频
```

**有异常隔离**：
```python
# ✅ 每个Handler独立执行
Handler 1: TextHandler - 成功 ✅
Handler 2: Live2DHandler - 失败 ❌ (异常被捕获)
Handler 3: AudioHandler - 成功 ✅ (不受影响)

# 结果：用户能看到文本，也能听到音频（只是Live2D不动）
```

**价值**：
- **健壮性**：单个功能失败不影响其他功能
- **用户体验**：部分功能降级，但整体可用
- **调试友好**：日志记录失败信息，便于排查

---

## 面试问答

### Q1: EventBus 和消息队列有什么区别？

**参考回答**：
> "**用途不同**：
>
> **EventBus**：用于**进程内**的事件分发，同步或异步调用，延迟 **< 1ms**。
>
> **消息队列**（如 RabbitMQ、Kafka）：用于**进程间**或**跨服务器**的消息传递，异步解耦，延迟 **10-100ms**。
>
> **在 Anima 中**，我使用 EventBus 是因为：
> 1. 所有 Handler 都在同一个进程内
> 2. 需要低延迟（< 1ms）
> 3. 不需要持久化
> 4. 不需要跨服务器
>
> 如果是**微服务架构**，我会选择消息队列（如 RabbitMQ），因为它支持：
> - 进程间通信
> - 消息持久化
> - 重试机制
> - 负载均衡"

### Q2: 如何保证事件的顺序性？

**参考回答**：
> "**EventBus 本身不保证顺序**，因为 Handler 是并发执行的。
>
> **但 Anima 中不需要严格保证顺序**，因为：
> 1. **文本事件**（HIGH 优先级）先处理，用户立即看到
> 2. **音频事件**（NORMAL 优先级）后处理，后台播放
> 3. **表情事件**（NORMAL 优先级）异步更新，不阻塞
>
> **如果需要保证顺序**，有 3 种方案：
> 1. **按优先级串行执行**：牺牲并发性，保证顺序
> 2. **事件编号（seq）**：前端根据 seq 排序显示
> 3. **Sequencer 模式**：引入序列化器，强制顺序执行
>
> 我选择了**方案 2**（事件编号），因为：
> - 保持并发性（性能好）
> - 前端可以灵活排序（用户体验好）
> - 不增加复杂度"

### Q3: 如何避免事件循环？

**参考回答**：
> "**事件循环**是指 Handler A 发布事件，Handler B 处理后又发布事件，导致无限循环。
>
> **在 Anima 中，我避免了这个问题**：
>
> 1. **单向数据流**：事件只从 Pipeline → Handlers → 前端，不反向
> 2. **事件类型隔离**：不同事件类型不互相触发
> 3. **Handler 不发布事件**：Handler 只负责发送数据到前端，不发布新事件
>
> **如果需要事件联动**，我会：
> 1. **使用有限状态机**：限制状态转换
> 2. **事件计数器**：超过阈值停止触发
> 3. **循环检测**：记录事件链，发现环就中断"

### Q4: 如何监控 EventBus 的性能？

**参考回答**：
> "我会添加 **3 个监控指标**：
>
> 1. **事件延迟**：从 emit 到 handle 执行的时间
>    ```python
>    start = time.perf_counter()
>    await handler.handle(event)
>    latency = time.perf_counter() - start
>    logger.info(f"Handler latency: {latency * 1000:.2f}ms")
>    ```
>
> 2. **队列长度**：每种事件类型的订阅者数量
>    ```python
>    logger.info(f"sentence subscribers: {len(self._subscriptions['sentence'])}")
>    ```
>
> 3. **失败率**：Handler 失败的频率
>    ```python
>    self.failure_count[event_type] += 1
>    logger.error(f"Handler failure rate: {self.failure_count[event_type] / total * 100:.2f}%")
>    ```
>
> 这些指标可以帮助我：
> - 发现性能瓶颈
> - 优化优先级设置
> - 提前发现 Handler 故障"

### Q5: EventBus 如何扩展到分布式系统？

**参考回答**：
> "**分布式 EventBus 有 3 种方案**：
>
> **方案 1：Redis Pub/Sub**
> - 优点：简单易用，性能好
> - 缺点：不持久化，不支持重试
> - 适用：实时通知，不要求可靠性
>
> **方案 2：RabbitMQ**
> - 优点：支持持久化、重试、确认机制
> - 缺点：复杂度高，延迟大
> - 适用：要求可靠性的场景
>
> **方案 3：Kafka**
> - 优点：高吞吐量，支持回溯
> - 缺点：复杂度最高
> - 适用：大数据场景
>
> **对于 Anima**，如果需要扩展到多服务器：
> 1. **使用 Redis Pub/Sub**：保留实时性
> 2. **添加消息队列**：对于可靠性和持久化要求高的功能
> 3. **混合架构**：Redis Pub/Sub + RabbitMQ"

---

## 性能优化

### 优化 1：惰性订阅

**问题**：每次 emit 都要查找订阅表

**优化**：缓存订阅表

```python
class EventBus:
    def __init__(self):
        self._subscriptions = {}
        self._subscription_cache = {}  # 缓存

    async def emit(self, event):
        # 优先从缓存读取
        if event.type in self._subscription_cache:
            handlers = self._subscription_cache[event.type]
        else:
            handlers = self._subscriptions.get(event.type, [])
            self._subscription_cache[event.type] = handlers

        # 处理...
```

### 优化 2：批量处理

**问题**：每个事件都触发一次 gather

**优化**：批量处理多个事件

```python
class EventBus:
    async def emit_batch(self, events: List[OutputEvent]):
        """批量发布事件"""
        tasks = []
        for event in events:
            for handler in self._handlers[event.type]:
                tasks.append(self._safe_handle(handler, event))

        await asyncio.gather(*tasks)
```

### 优化 3：事件去重

**问题**：重复的事件会重复处理

**优化**：添加去重机制

```python
class EventBus:
    def __init__(self):
        self._processed_events = set()  # 已处理的事件
        self._lock = asyncio.Lock()

    async def emit(self, event):
        # 生成事件唯一标识
        event_id = f"{event.type}_{event.seq}"

        async with self._lock:
            if event_id in self._processed_events:
                return  # 跳过重复事件

            self._processed_events.add(event_id)

        # 定期清理（避免内存泄漏）
        if len(self._processed_events) > 10000:
            self._processed_events.clear()
```

---

## 相关文档

- [设计模式详解](./design-patterns.md) - 观察者模式详细说明
- [数据流设计](./data-flow.md) - 完整的数据流架构
- [技术亮点](../overview/highlights.md) - 技术亮点总结

---

**最后更新**: 2026-02-28
