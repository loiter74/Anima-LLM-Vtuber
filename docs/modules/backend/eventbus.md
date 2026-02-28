# 事件总线

> EventBus 和 EventRouter 的完整实现

---

## 目录

1. [EventBus 实现](#eventbus-实现)
2. [EventRouter 实现](#eventrouter-实现)
3. [事件类型](#事件类型)
4. [使用示例](#使用示例)

---

## EventBus 实现

### 核心功能

```python
# src/anima/eventbus/bus.py
from typing import Dict, List
from dataclasses import dataclass
from enum import Enum
import asyncio

class EventPriority(Enum):
    HIGH = 1
    NORMAL = 2
    LOW = 3

@dataclass
class Subscription:
    event_type: str
    handler: 'BaseHandler'
    priority: EventPriority

class EventBus:
    """事件总线"""

    def __init__(self):
        self._subscriptions: Dict[str, List[Subscription]] = {}

    def subscribe(
        self,
        event_type: str,
        handler: 'BaseHandler',
        priority: EventPriority = EventPriority.NORMAL
    ) -> Subscription:
        """订阅事件"""
        subscription = Subscription(event_type, handler, priority)

        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []

        self._subscriptions[event_type].append(subscription)

        # 按优先级排序
        self._subscriptions[event_type].sort(
            key=lambda sub: sub.priority.value
        )

        return subscription

    def unsubscribe(self, subscription: Subscription):
        """取消订阅"""
        event_type = subscription.event_type
        if event_type in self._subscriptions:
            try:
                self._subscriptions[event_type].remove(subscription)
            except ValueError:
                pass

    async def emit(self, event: 'OutputEvent'):
        """发布事件"""
        event_type = event.type

        if event_type not in self._subscriptions:
            return

        subscriptions = self._subscriptions[event_type]

        # 并发执行，异常隔离
        tasks = []
        for subscription in subscriptions:
            task = self._safe_handle(subscription.handler, event)
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_handle(self, handler, event):
        """安全调用（异常隔离）"""
        try:
            await handler.handle(event)
        except Exception as e:
            logger.error(f"Handler failed: {e}")

    def clear(self):
        """清空所有订阅"""
        self._subscriptions.clear()
```

---

## EventRouter 实现

### 核心功能

```python
# src/anima/eventbus/router.py
from typing import List

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
        """注册 Handler"""
        subscription = self.event_bus.subscribe(
            event_type,
            handler,
            priority
        )
        self._handlers.append(handler)
        return self

    def setup(self):
        """设置路由"""
        logger.info(f"Setting up {len(self._handlers)} handlers")

    def clear(self):
        """清理路由"""
        self._handlers.clear()
        self.event_bus.clear()
```

---

## 事件类型

### 定义

```python
# src/anima/core/events.py
class EventType(str, Enum):
    SENTENCE = "sentence"
    AUDIO = "audio"
    AUDIO_WITH_EXPRESSION = "audio_with_expression"
    EXPRESSION = "expression"
    CONTROL = "control"
    ERROR = "error"
```

### OutputEvent

```python
@dataclass
class OutputEvent:
    type: str
    data: Any
    seq: int
    metadata: Dict = None
```

---

## 使用示例

### 注册 Handler

```python
# 在 ConversationOrchestrator 中
from anima.eventbus import EventBus, EventRouter, EventPriority

# 创建 EventBus 和 EventRouter
event_bus = EventBus()
event_router = EventRouter(event_bus)

# 注册 Handlers
event_router.register("sentence", TextHandler(ws.send), EventPriority.HIGH)
event_router.register("audio", AudioHandler(ws.send), EventPriority.NORMAL)
event_router.register("expression", ExpressionHandler(ws.send), EventPriority.NORMAL)
```

### 发布事件

```python
# 发布文本事件
await event_bus.emit(OutputEvent(
    type="sentence",
    data="你好！",
    seq=1
))

# 发布音频事件
await event_bus.emit(OutputEvent(
    type="audio",
    data=base64_audio,
    seq=2
))
```

---

## 总结

### EventBus 特点

- ✅ **解耦**：发布者和订阅者互不依赖
- ✅ **优先级**：支持事件优先级
- ✅ **异常隔离**：单个失败不影响其他
- ✅ **动态订阅**：运行时注册/取消

---

**最后更新**: 2026-02-28
