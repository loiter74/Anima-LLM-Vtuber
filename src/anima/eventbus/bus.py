"""
EventBus - 事件总线
基于观察者模式的事件分发系统
支持优先级、异常隔离、取消订阅
"""

from typing import TYPE_CHECKING, List, Callable, Dict, Optional, Any
from loguru import logger
from enum import Enum

if TYPE_CHECKING:
    from anima.core import OutputEvent


EventHandler = Callable[["OutputEvent"], None]


class EventPriority(int, Enum):
    """事件处理器优先级（数值越大优先级越高）"""
    LOWEST = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    HIGHEST = 100
    MONITOR = 200  # 监控器，最后执行


class Subscription:
    """
    订阅信息容器
    
    用于跟踪和管理单个订阅
    """
    
    def __init__(
        self,
        event_type: str,
        handler: EventHandler,
        priority: int = EventPriority.NORMAL,
        is_global: bool = False,
    ):
        self.event_type = event_type
        self.handler = handler
        self.priority = priority
        self.is_global = is_global
        self.is_active = True
    
    def __repr__(self) -> str:
        return f"Subscription({self.event_type}, priority={self.priority}, active={self.is_active})"


class EventBus:
    """
    事件总线
    
    用于在 Pipeline 和 Handler 之间分发事件
    支持：
    - 订阅/取消订阅（返回订阅对象便于管理）
    - 按事件类型过滤
    - 优先级排序
    - 异步处理
    - 异常隔离
    - 全局订阅
    
    使用示例:
        bus = EventBus()
        
        # 方式1：简单订阅
        bus.subscribe("sentence", my_handler)
        
        # 方式2：带优先级订阅
        sub = bus.subscribe("audio", my_audio_handler, priority=EventPriority.HIGH)
        
        # 方式3：取消订阅
        bus.unsubscribe(sub)
        
        # 发射事件
        await bus.emit(OutputEvent(type="sentence", data="Hello"))
    """
    
    def __init__(self):
        """初始化事件总线"""
        # 按事件类型分组的订阅者 {event_type: [(priority, handler, subscription)]}
        self._subscribers: Dict[str, List[tuple]] = {}
        # 全局订阅者 [(priority, handler, subscription)]
        self._global_subscribers: List[tuple] = []
        # 所有订阅的快速查找 {id: subscription}
        self._all_subscriptions: Dict[int, Subscription] = {}
        # 用于生成唯一订阅 ID
        self._subscription_counter = 0
    
    def _get_next_id(self) -> int:
        """生成下一个订阅 ID"""
        self._subscription_counter += 1
        return self._subscription_counter
    
    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        priority: int = EventPriority.NORMAL,
    ) -> Subscription:
        """
        订阅特定类型的事件
        
        Args:
            event_type: 事件类型
            handler: 处理函数（同步或异步）
            priority: 优先级（数值越大越先执行）
            
        Returns:
            Subscription: 订阅对象，可用于取消订阅
        """
        # 创建订阅对象
        sub_id = self._get_next_id()
        subscription = Subscription(
            event_type=event_type,
            handler=handler,
            priority=priority,
            is_global=False,
        )
        self._all_subscriptions[sub_id] = subscription
        
        # 添加到对应事件类型的列表
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        
        # 按优先级插入（保持有序）
        entry = (-priority, handler, subscription)  # 负数用于降序排序
        self._subscribers[event_type].append(entry)
        self._subscribers[event_type].sort(key=lambda x: x[0])
        
        logger.debug(f"EventBus: 订阅事件 '{event_type}' (priority={priority})")
        return subscription
    
    def subscribe_all(
        self,
        handler: EventHandler,
        priority: int = EventPriority.NORMAL,
    ) -> Subscription:
        """
        订阅所有事件
        
        Args:
            handler: 处理函数
            priority: 优先级
            
        Returns:
            Subscription: 订阅对象
        """
        sub_id = self._get_next_id()
        subscription = Subscription(
            event_type="*",
            handler=handler,
            priority=priority,
            is_global=True,
        )
        self._all_subscriptions[sub_id] = subscription
        
        entry = (-priority, handler, subscription)
        self._global_subscribers.append(entry)
        self._global_subscribers.sort(key=lambda x: x[0])
        
        logger.debug(f"EventBus: 订阅所有事件 (priority={priority})")
        return subscription
    
    def unsubscribe(self, subscription: Subscription) -> bool:
        """
        取消订阅
        
        Args:
            subscription: 订阅对象（由 subscribe 返回）
            
        Returns:
            bool: 是否成功取消
        """
        if not subscription.is_active:
            return False
        
        subscription.is_active = False
        
        if subscription.is_global:
            # 从全局订阅中移除
            for i, (_, _, sub) in enumerate(self._global_subscribers):
                if sub is subscription:
                    self._global_subscribers.pop(i)
                    logger.debug("EventBus: 取消全局订阅")
                    return True
        else:
            # 从特定事件类型中移除
            event_type = subscription.event_type
            if event_type in self._subscribers:
                for i, (_, _, sub) in enumerate(self._subscribers[event_type]):
                    if sub is subscription:
                        self._subscribers[event_type].pop(i)
                        logger.debug(f"EventBus: 取消订阅 '{event_type}'")
                        return True
        
        return False
    
    def unsubscribe_by_type(self, event_type: str) -> int:
        """
        取消特定事件类型的所有订阅
        
        Args:
            event_type: 事件类型
            
        Returns:
            int: 取消的订阅数量
        """
        count = 0
        if event_type in self._subscribers:
            count = len(self._subscribers[event_type])
            for _, _, sub in self._subscribers[event_type]:
                sub.is_active = False
            del self._subscribers[event_type]
        
        logger.debug(f"EventBus: 取消 '{event_type}' 的所有订阅 ({count} 个)")
        return count
    
    async def emit(self, event: "OutputEvent") -> int:
        """
        发射事件
        
        Args:
            event: 输出事件
            
        Returns:
            int: 成功处理的处理器数量
        """
        processed_count = 0
        
        # 分发到特定类型的订阅者
        if event.type in self._subscribers:
            for _, handler, sub in self._subscribers[event.type]:
                if not sub.is_active:
                    continue
                    
                try:
                    result = handler(event)
                    if hasattr(result, '__await__'):
                        await result
                    processed_count += 1
                except Exception as e:
                    logger.error(
                        f"EventBus handler 错误 [{event.type}]: "
                        f"{handler.__name__ if hasattr(handler, '__name__') else handler} - {e}"
                    )
        
        # 分发到全局订阅者
        for _, handler, sub in self._global_subscribers:
            if not sub.is_active:
                continue
                
            try:
                result = handler(event)
                if hasattr(result, '__await__'):
                    await result
                processed_count += 1
            except Exception as e:
                logger.error(
                    f"EventBus 全局 handler 错误: "
                    f"{handler.__name__ if hasattr(handler, '__name__') else handler} - {e}"
                )
        
        return processed_count
    
    def emit_sync(self, event: "OutputEvent") -> int:
        """
        同步发射事件（仅用于同步处理器）
        
        Args:
            event: 输出事件
            
        Returns:
            int: 成功处理的处理器数量
        """
        processed_count = 0
        
        if event.type in self._subscribers:
            for _, handler, sub in self._subscribers[event.type]:
                if not sub.is_active:
                    continue
                    
                try:
                    result = handler(event)
                    # 忽略协程结果
                    if not hasattr(result, '__await__'):
                        processed_count += 1
                except Exception as e:
                    logger.error(f"EventBus 同步 handler 错误: {e}")
        
        return processed_count
    
    def clear(self) -> None:
        """清除所有订阅"""
        # 标记所有订阅为非活跃
        for sub in self._all_subscriptions.values():
            sub.is_active = False
        
        self._subscribers.clear()
        self._global_subscribers.clear()
        self._all_subscriptions.clear()
        logger.debug("EventBus: 已清除所有订阅")
    
    def has_subscribers(self, event_type: str) -> bool:
        """检查是否有特定事件类型的订阅者"""
        return event_type in self._subscribers and len(self._subscribers[event_type]) > 0
    
    def get_subscriber_count(self, event_type: Optional[str] = None) -> int:
        """
        获取订阅者数量
        
        Args:
            event_type: 事件类型（None 表示所有）
            
        Returns:
            int: 订阅者数量
        """
        if event_type:
            return len(self._subscribers.get(event_type, []))
        
        count = len(self._global_subscribers)
        for handlers in self._subscribers.values():
            count += len(handlers)
        return count
    
    @property
    def subscriber_count(self) -> int:
        """获取订阅者总数"""
        return self.get_subscriber_count()
    
    def get_event_types(self) -> List[str]:
        """获取所有已订阅的事件类型"""
        return list(self._subscribers.keys())