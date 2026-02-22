/**
 * EventService - 基础事件发射器
 * 提供类型安全的发布-订阅模式
 *
 * 职责：
 * - 事件订阅和取消订阅
 * - 事件发射
 * - 生命周期管理
 */

type EventCallback<T = any> = (data: T) => void

/**
 * Generic EventService with type-safe events
 * @template TEvents - Events interface mapping event names to their data types
 */
export class EventService<TEvents extends Record<string, any> = Record<string, any>> {
  private listeners: Map<string, Set<EventCallback>> = new Map()
  private onceListeners: Map<string, Set<EventCallback>> = new Map()

  /**
   * 订阅事件
   */
  on<K extends keyof TEvents>(
    event: K,
    callback: EventCallback<TEvents[K]>
  ): () => void {
    const eventKey = String(event)
    if (!this.listeners.has(eventKey)) {
      this.listeners.set(eventKey, new Set())
    }
    this.listeners.get(eventKey)!.add(callback)

    // 返回取消订阅函数
    return () => this.off(event, callback)
  }

  /**
   * 取消订阅事件
   */
  off<K extends keyof TEvents>(
    event: K,
    callback: EventCallback<TEvents[K]>
  ): void {
    const eventKey = String(event)
    const handlers = this.listeners.get(eventKey)
    if (handlers) {
      handlers.delete(callback as any)
      if (handlers.size === 0) {
        this.listeners.delete(eventKey)
      }
    }
  }

  /**
   * 订阅一次性事件
   */
  once<K extends keyof TEvents>(
    event: K,
    callback: EventCallback<TEvents[K]>
  ): () => void {
    const eventKey = String(event)
    if (!this.onceListeners.has(eventKey)) {
      this.onceListeners.set(eventKey, new Set())
    }
    this.onceListeners.get(eventKey)!.add(callback as any)

    return () => this.offOnce(event, callback)
  }

  /**
   * 取消一次性订阅
   */
  private offOnce<K extends keyof TEvents>(
    event: K,
    callback: EventCallback<TEvents[K]>
  ): void {
    const eventKey = String(event)
    const handlers = this.onceListeners.get(eventKey)
    if (handlers) {
      handlers.delete(callback as any)
      if (handlers.size === 0) {
        this.onceListeners.delete(eventKey)
      }
    }
  }

  /**
   * 发射事件
   */
  emit<K extends keyof TEvents>(event: K, data?: TEvents[K]): void {
    const eventKey = String(event)

    // 触发普通监听器
    const handlers = this.listeners.get(eventKey)
    if (handlers) {
      handlers.forEach(callback => {
        try {
          callback(data)
        } catch (error) {
          console.error(`[EventService] Error in event handler for "${eventKey}":`, error)
        }
      })
    }

    // 触发一次性监听器
    const onceHandlers = this.onceListeners.get(eventKey)
    if (onceHandlers) {
      onceHandlers.forEach(callback => {
        try {
          callback(data)
        } catch (error) {
          console.error(`[EventService] Error in once handler for "${eventKey}":`, error)
        }
      })
      // 清空一次性监听器
      this.onceListeners.delete(eventKey)
    }
  }

  /**
   * 清除所有事件监听器
   */
  removeAllListeners(event?: keyof TEvents): void {
    if (event) {
      this.listeners.delete(String(event))
      this.onceListeners.delete(String(event))
    } else {
      this.listeners.clear()
      this.onceListeners.clear()
    }
  }

  /**
   * 获取事件监听器数量
   */
  listenerCount(event: keyof TEvents): number {
    const eventKey = String(event)
    const handlers = this.listeners.get(eventKey)
    const onceHandlers = this.onceListeners.get(eventKey)
    return (handlers?.size || 0) + (onceHandlers?.size || 0)
  }

  /**
   * 销毁服务
   */
  destroy(): void {
    this.removeAllListeners()
  }
}
