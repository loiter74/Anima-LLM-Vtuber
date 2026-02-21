/**
 * SocketService
 * High-level service for Socket.IO communication
 * Wraps SocketClient with application-specific logic
 */

import { SocketClient } from '@/lib/socket/SocketClient'
import { useConnectionStore } from '@/shared/state/stores/connectionStore'
import { logger } from '@/shared/utils/logger'
import type { SocketEvents, SocketEmits } from '@/shared/types/socket'
import { CONTROL_SIGNALS } from '@/shared/constants/events'

export class SocketService {
  private client: SocketClient
  private eventHandlers: Map<keyof SocketEvents, Set<Function>> = new Map()

  constructor(url?: string) {
    this.client = new SocketClient(url)
  }

  /**
   * Connect to the server
   */
  async connect(): Promise<void> {
    const { setStatus, setError, setSessionId } = useConnectionStore.getState()

    try {
      setStatus('connecting')
      setError(null)

      await this.client.connect()

      // Register built-in event handlers
      this.registerBuiltInHandlers()

      setStatus('connected')
      setSessionId(this.client.id ?? null)

      logger.debug('[SocketService] Connected successfully')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Connection failed'
      setStatus('error')
      setError(message)
      throw error
    }
  }

  /**
   * Disconnect from the server
   */
  disconnect(): void {
    const { setStatus, setSessionId } = useConnectionStore.getState()

    this.client.disconnect()

    // Clear all event handlers
    this.eventHandlers.clear()

    setStatus('disconnected')
    setSessionId(null)

    logger.debug('[SocketService] Disconnected')
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
      // Register with underlying client only once per event
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      this.client.on(event as any, ((data: any) => {
        this.notifyHandlers(event, data)
      }) as any)
    }

    const handlers = this.eventHandlers.get(event)!
    handlers.add(callback)

    logger.debug(`[SocketService] Registered handler for "${event}", total: ${handlers.size}`)
  }

  /**
   * Unregister event listener
   */
  off<Event extends keyof SocketEvents>(
    event: Event,
    callback?: SocketEvents[Event]
  ): void {
    if (!this.eventHandlers.has(event)) {
      return
    }

    const handlers = this.eventHandlers.get(event)!

    if (callback) {
      handlers.delete(callback)
      logger.debug(`[SocketService] Removed handler for "${event}", remaining: ${handlers.size}`)
    } else {
      handlers.clear()
      logger.debug(`[SocketService] Cleared all handlers for "${event}"`)
    }

    // Remove from map if no handlers left
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

    // Connection established
    this.client.on('connection-established', (data) => {
      logger.debug('[SocketService] Connection established:', data)
    })

    // Control events
    this.client.on('control', (data) => {
      logger.debug('[SocketService] Control signal:', data.text)

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

      // Forward to registered handlers
      this.notifyHandlers('control', data)
    })

    // Error events
    this.client.on('error', (data) => {
      logger.error('[SocketService] Server error:', data.message)
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
    if (!handlers) {
      return
    }

    for (const handler of handlers) {
      try {
        ;(handler as any)(data)
      } catch (error) {
        logger.error(`[SocketService] Error in handler for "${event}":`, error)
      }
    }
  }

  /**
   * Get socket ID
   */
  get id(): string | undefined {
    return this.client.id
  }

  /**
   * Check if connected
   */
  get connected(): boolean {
    return this.client.connected
  }

  /**
   * Get raw SocketClient instance
   */
  get raw(): SocketClient {
    return this.client
  }
}
