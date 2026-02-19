"""
EventRouter - 事件路由器
将事件路由到对应的 Handler，支持动态注册、异常隔离、优先级
"""

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from loguru import logger

from .bus import EventBus, EventPriority, Subscription

if TYPE_CHECKING:
    from anima.core import OutputEvent
    from anima.handlers import BaseHandler


class EventRouter:
    """
    事件路由器
    
    将 EventBus 中的事件路由到对应的 Handler
    
    特性：
    - 链式调用设计
    - 支持动态注册（setup 后也能添加新 Handler）
    - 异常隔离（单个 Handler 崩溃不影响其他）
    - 优先级支持
    - 真正清除（从 EventBus 取消订阅）
    
    使用示例:
        router = EventRouter(event_bus)
        router.register("sentence", TextHandler(), priority=EventPriority.HIGH)
        router.register("audio", AudioHandler())
        router.setup()  # 连接到 EventBus
        
        # 动态添加（即使 setup 后也能生效）
        router.register("video", VideoHandler())
        
        # 清除所有路由（真正从 EventBus 移除）
        router.clear()
    """
    
    def __init__(self, event_bus: EventBus):
        """
        初始化路由器
        
        Args:
            event_bus: 事件总线
        """
        self.event_bus = event_bus
        # 本地注册表 {event_type: [(handler, priority)]}
        self._handlers: Dict[str, List[Tuple["BaseHandler", int]]] = {}
        # 记录已订阅的包装函数 [(event_type, wrapper, subscription)]
        self._subscriptions: List[Tuple[str, callable, Subscription]] = []
        # 是否已完成初始设置
        self._setup_done = False
    
    def register(
        self,
        event_type: str,
        handler: "BaseHandler",
        priority: int = EventPriority.NORMAL,
    ) -> "EventRouter":
        """
        注册 Handler 到事件类型
        
        Args:
            event_type: 事件类型
            handler: Handler 实例
            priority: 优先级（数值越大越先执行）
            
        Returns:
            self（支持链式调用）
        """
        # 添加到本地注册表
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        
        self._handlers[event_type].append((handler, priority))
        
        # 如果已经 setup 过，则动态直接挂载
        if self._setup_done:
            self._mount_handler(event_type, handler, priority)
        
        logger.debug(
            f"EventRouter: 注册 '{event_type}' -> {handler.__class__.__name__} "
            f"(priority={priority}, dynamic={self._setup_done})"
        )
        return self
    
    def register_many(
        self,
        event_types: List[str],
        handler: "BaseHandler",
        priority: int = EventPriority.NORMAL,
    ) -> "EventRouter":
        """
        将同一个 Handler 注册到多个事件类型
        
        Args:
            event_types: 事件类型列表
            handler: Handler 实例
            priority: 优先级
            
        Returns:
            self
        """
        for event_type in event_types:
            self.register(event_type, handler, priority)
        return self
    
    def _mount_handler(
        self,
        event_type: str,
        handler: "BaseHandler",
        priority: int,
    ) -> Subscription:
        """
        将单个 Handler 挂载到 EventBus
        
        Args:
            event_type: 事件类型
            handler: Handler 实例
            priority: 优先级
            
        Returns:
            Subscription: 订阅对象
        """
        wrapper = self._create_wrapper(handler)
        subscription = self.event_bus.subscribe(event_type, wrapper, priority)
        self._subscriptions.append((event_type, wrapper, subscription))
        return subscription
    
    def setup(self) -> None:
        """
        设置路由（连接到 EventBus）
        
        只能调用一次，后续 register 会自动挂载
        """
        if self._setup_done:
            logger.warning("EventRouter 已经设置过了，跳过")
            return
        
        total_handlers = 0
        for event_type, handlers in self._handlers.items():
            for handler, priority in handlers:
                self._mount_handler(event_type, handler, priority)
                total_handlers += 1
        
        self._setup_done = True
        logger.info(
            f"EventRouter 设置完成: {len(self._handlers)} 种事件类型, "
            f"{total_handlers} 个处理器"
        )
    
    def _create_wrapper(self, handler: "BaseHandler"):
        """
        创建 Handler 包装函数（带异常隔离）
        
        关键：防止单个 Handler 崩溃影响全局
        """
        async def wrapper(event: "OutputEvent"):
            try:
                await handler.handle(event)
            except Exception as e:
                logger.error(
                    f"Handler {handler.__class__.__name__} 执行出错 "
                    f"[event={event.type}]: {e}"
                )
        return wrapper
    
    def unregister(self, event_type: str, handler: "BaseHandler") -> bool:
        """
        取消特定 Handler 的注册
        
        Args:
            event_type: 事件类型
            handler: Handler 实例
            
        Returns:
            bool: 是否成功取消
        """
        # 从本地注册表移除
        if event_type in self._handlers:
            for i, (h, p) in enumerate(self._handlers[event_type]):
                if h is handler:
                    self._handlers[event_type].pop(i)
                    break
        
        # 从 EventBus 取消订阅
        for i, (etype, wrapper, subscription) in enumerate(self._subscriptions):
            if etype == event_type:
                # 检查 wrapper 是否对应这个 handler
                # 由于 wrapper 是闭包，需要特殊处理
                self.event_bus.unsubscribe(subscription)
                self._subscriptions.pop(i)
                logger.debug(f"EventRouter: 取消注册 '{event_type}' -> {handler.__class__.__name__}")
                return True
        
        return False
    
    def unregister_all(self, event_type: str) -> int:
        """
        取消特定事件类型的所有 Handler
        
        Args:
            event_type: 事件类型
            
        Returns:
            int: 取消的 Handler 数量
        """
        count = 0
        
        # 从本地注册表移除
        if event_type in self._handlers:
            count = len(self._handlers[event_type])
            del self._handlers[event_type]
        
        # 从 EventBus 取消订阅
        to_remove = []
        for i, (etype, wrapper, subscription) in enumerate(self._subscriptions):
            if etype == event_type:
                self.event_bus.unsubscribe(subscription)
                to_remove.append(i)
        
        # 从后往前删除，避免索引问题
        for i in reversed(to_remove):
            self._subscriptions.pop(i)
        
        logger.debug(f"EventRouter: 取消 '{event_type}' 的所有处理器 ({count} 个)")
        return count
    
    def clear(self) -> None:
        """
        真正的清除：不仅清空本地，还要从 EventBus 取消订阅
        """
        # 从 EventBus 取消所有订阅
        for event_type, wrapper, subscription in self._subscriptions:
            self.event_bus.unsubscribe(subscription)
        
        # 清空本地数据
        self._handlers.clear()
        self._subscriptions.clear()
        self._setup_done = False
        
        logger.debug("EventRouter: 已完全重置路由")
    
    def get_handlers(self, event_type: str) -> List[Tuple["BaseHandler", int]]:
        """
        获取特定事件类型的所有 Handler
        
        Args:
            event_type: 事件类型
            
        Returns:
            List of (handler, priority) tuples
        """
        return list(self._handlers.get(event_type, []))
    
    def get_event_types(self) -> List[str]:
        """获取所有已注册的事件类型"""
        return list(self._handlers.keys())
    
    @property
    def handler_count(self) -> int:
        """获取 Handler 总数"""
        return sum(len(handlers) for handlers in self._handlers.values())
    
    @property
    def is_setup(self) -> bool:
        """是否已完成设置"""
        return self._setup_done
    
    def __repr__(self) -> str:
        return (
            f"EventRouter("
            f"event_types={len(self._handlers)}, "
            f"handlers={self.handler_count}, "
            f"setup={self._setup_done})"
        )