/**
 * SocketService
 * Socket.IO 高级服务包装（单例模式）
 */

import { SocketClient } from './SocketClient'
import { useConnectionStore } from '../stores/connectionStore'
import type { SocketEvents, SocketEmits } from '../types'
import { CONTROL_SIGNALS } from '../constants/events'

// 全局单例
let globalClient: SocketClient | null = null
let globalInitialized = false

export class SocketService {
  private client: SocketClient
  private eventHandlers: Map<keyof SocketEvents, Set<Function>> = new Map()

  constructor(url?: string) {
    if (!globalClient) {
      globalClient = new SocketClient(url)
    }
    this.client = globalClient
  }

  /**
   * Connect to the server
   */
  async connect(): Promise<void> {
    if (globalInitialized) {
      return
    }

    const { setStatus, setError, setSessionId } = useConnectionStore.getState()

    try {
      globalInitialized = true
      setStatus('connecting')
      setError(null)

      await this.client.connect()
      this.registerBuiltInHandlers()

      setStatus('connected')
      setSessionId(this.client.id ?? null)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Connection failed'
      setStatus('error')
      setError(message)
      globalInitialized = false
      throw error
    }
  }

  /**
   * Disconnect from the server
   */
  disconnect(): void {
    const { setStatus, setSessionId } = useConnectionStore.getState()

    this.client.disconnect()
    this.eventHandlers.clear()

    setStatus('disconnected')
    setSessionId(null)
    globalInitialized = false
  }

  /**
   * Register event listener
   */
  on<Event extends keyof SocketEvents>(
    event: Event,
    callback: SocketEvents[Event]
  ): void {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, new Set())
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      this.client.on(event as any, ((data: any) => {
        this.notifyHandlers(event, data)
      }) as any)
    }

    const handlers = this.eventHandlers.get(event)!
    handlers.add(callback)
  }

  /**
   * Unregister event listener
   */
  off<Event extends keyof SocketEvents>(
    event: Event,
    callback?: SocketEvents[Event]
  ): void {
    if (!this.eventHandlers.has(event)) return

    const handlers = this.eventHandlers.get(event)!

    if (callback) {
      handlers.delete(callback)
    } else {
      handlers.clear()
    }

    if (handlers.size === 0) {
      this.eventHandlers.delete(event)
    }
  }

  /**
   * Emit event to server
   */
  emit<Event extends keyof SocketEmits>(
    event: Event,
    ...args: Parameters<SocketEmits[Event]>
  ): void {
    this.client.emit(event, ...args)
  }

  /**
   * Register built-in event handlers
   */
  private registerBuiltInHandlers(): void {
    const { setStatus, setError } = useConnectionStore.getState()

    this.client.on('connection-established', (data) => {
      console.debug('[SocketService] Connection established:', data)
    })

    this.client.on('control', (data) => {
      console.debug('[SocketService] Control signal:', data.text)

      switch (data.text) {
        case CONTROL_SIGNALS.START_MIC:
          setStatus('connected')
          break
        case CONTROL_SIGNALS.INTERRUPT:
        case CONTROL_SIGNALS.INTERRUPTED:
          setStatus('disconnected')
          break
        case CONTROL_SIGNALS.NO_AUDIO_DATA:
        case CONTROL_SIGNALS.CONVERSATION_END:
          setStatus('connected')
          break
        case CONTROL_SIGNALS.CONVERSATION_START:
        case CONTROL_SIGNALS.MIC_AUDIO_END:
          setStatus('connected')
          break
      }

      this.notifyHandlers('control', data)
    })

    this.client.on('error', (data) => {
      console.error('[SocketService] Server error:', data.message)
      setError(data.message)
      this.notifyHandlers('error', data)
    })
  }

  /**
   * Notify all registered handlers for an event
   */
  private notifyHandlers<Event extends keyof SocketEvents>(
    event: Event,
    data: Parameters<SocketEvents[Event]>[0]
  ): void {
    const handlers = this.eventHandlers.get(event)
    if (!handlers) return

    for (const handler of handlers) {
      try {
        ;(handler as any)(data)
      } catch (error) {
        console.error(`[SocketService] Error in handler for "${event}":`, error)
      }
    }
  }

  /** Get socket ID */
  get id(): string | undefined {
    return this.client.id
  }

  /** Check if connected */
  get connected(): boolean {
    return this.client.connected
  }

  /** Get raw SocketClient instance */
  get raw(): SocketClient {
    return this.client
  }

  /** Get raw socket instance (for advanced usage) */
  get socket(): any {
    return this.client.raw
  }
}
