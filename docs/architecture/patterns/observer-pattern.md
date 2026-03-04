# Observer Pattern（观察者模式）

> 🎓 **面试重点** - 设计模式实际应用
> 
> ⚠️ **注意**：部分示例代码使用旧的组件名称，这些在 v0.6.0 (2026-03-01) 已被新架构替代。
> 请参考 [CLAUDE.md](../../../CLAUDE.md) 了解最新的架构。

---

## 4. Observer Pattern（观察者模式）

### 定义

观察者模式定义对象间的一对多依赖关系，当一个对象状态改变时，所有依赖它的对象都会收到通知。

### 项目应用

在 Anima 中，EventBus 实现了观察者模式，用于**事件发布和订阅**。

### 代码实现

#### 4.1 EventBus 实现

```python
# src/anima/eventbus/bus.py
from typing import Dict, List, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
import asyncio

class EventPriority(Enum):
    """事件优先级"""
    HIGH = 1
    NORMAL = 2
    LOW = 3

@dataclass
class Subscription:
    """订阅信息"""
    event_type: str
    handler: Callable  # Handler
    priority: EventPriority

class EventBus:
    """事件总线（观察者模式的 Subject）"""

    def __init__(self):
        # 订阅表: {event_type: [Subscription]}
        self._subscriptions: Dict[str, List[Subscription]] = {}

    def subscribe(
        self,
        event_type: str,
        handler: Callable,
        priority: EventPriority = EventPriority.NORMAL
    ) -> Subscription:
        """
        订阅事件（注册观察者）

        Args:
            event_type: 事件类型
            handler: 处理函数
            priority: 优先级

        Returns:
            订阅对象（用于取消订阅）
        """
        subscription = Subscription(event_type, handler, priority)

        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []

        self._subscriptions[event_type].append(subscription)

        # 按优先级排序（数字越小优先级越高）
        self._subscriptions[event_type].sort(
            key=lambda sub: sub.priority.value
        )

        return subscription

    def unsubscribe(self, subscription: Subscription):
        """取消订阅"""
        event_type = subscription.event_type

        if event_type in self._subscriptions:
            self._subscriptions[event_type].remove(subscription)

    async def emit(self, event: 'OutputEvent'):
        """
        发布事件（通知所有观察者）

        Args:
            event: 事件对象
        """
        event_type = event.type

        if event_type not in self._subscriptions:
            return

        # 获取所有订阅者
        subscriptions = self._subscriptions[event_type]

        # 并发调用所有 Handler（异常隔离）
        tasks = []
        for subscription in subscriptions:
            task = self._safe_handle(subscription.handler, event)
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_handle(self, handler: Callable, event: 'OutputEvent'):
        """
        安全调用 Handler（异常隔离）

        单个 Handler 失败不影响其他
        """
        try:
            await handler.handle(event)
        except Exception as e:
            logger.error(f"Handler failed: {e}")
            # 不中断其他 Handler
```

#### 4.2 Handler 实现

```python
# src/anima/handlers/text_handler.py
from .base_handler import BaseHandler

class TextHandler(BaseHandler):
    """文本事件处理器（观察者）"""

    def __init__(self, websocket_send):
        self.send = websocket_send

    async def handle(self, event: OutputEvent):
        """处理文本事件"""
        await self.send({
            "type": "text",
            "text": event.data,
            "seq": event.seq
        })
```

#### 4.3 使用示例

```python
# 创建 EventBus
event_bus = EventBus()

# 注册观察者
event_bus.subscribe("sentence", TextHandler(ws.send), EventPriority.HIGH)
event_bus.subscribe("audio", AudioHandler(ws.send), EventPriority.NORMAL)

# 发布事件（所有订阅者都会收到）
await event_bus.emit(OutputEvent(
    type="sentence",
    data="你好",
    seq=1
))
```

### 优势

1. **解耦**：发布者和订阅者互不依赖
2. **优先级**：控制处理顺序
3. **异常隔离**：单个失败不影响其他
4. **动态订阅**：运行时注册/取消

### 面试要点

**Q: EventBus 和简单的回调函数有什么区别？**
> A: **关键区别在于解耦和扩展性**：
>
> 简单回调：
> ```python
> class Agent:
>     def __init__(self):
>         self.on_text = None  # 回调函数
>
>     async def chat(self, text):
>         response = await self.llm.generate(text)
>         if self.on_text:  # 调用回调
>             await self.on_text(response)
>
> # 问题：
> # 1. 只能有一个回调
> # 2. Agent 需要知道回调的存在
> ```
>
> EventBus：
> ```python
> # Agent 不需要知道谁在监听
> await event_bus.emit(OutputEvent(type="sentence", data=response))
>
> # 可以有多个订阅者
> event_bus.subscribe("sentence", TextHandler(...))
> event_bus.subscribe("sentence", LogHandler(...))
> event_bus.subscribe("sentence", AnalyticsHandler(...))
> ```
>
> 这体现了**观察者模式的核心价值**——发布者和订阅者的解耦。

---