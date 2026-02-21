/**
 * useSocket Hook
 * Manages Socket.IO connection and event listeners
 */

import { useEffect, useRef, useCallback } from 'react'
import { SocketService } from '../services/SocketService'
import { useConnectionStore } from '@/shared/state/stores/connectionStore'
import { logger } from '@/shared/utils/logger'
import type { SocketEvents, SocketEmits } from '@/shared/types/socket'

export interface UseSocketOptions {
  autoConnect?: boolean
  url?: string
}

export interface UseSocketReturn {
  socket: SocketService | null
  isConnected: boolean
  connect: () => void
  disconnect: () => void
  emit: <Event extends keyof SocketEmits>(
    event: Event,
    ...args: Parameters<SocketEmits[Event]>
  ) => void
}

/**
 * Hook for Socket.IO connection management
 */
export function useSocket(
  options: UseSocketOptions = {}
): UseSocketReturn {
  const { autoConnect = true, url } = options
  const serviceRef = useRef<SocketService | null>(null)

  // Initialize socket service
  useEffect(() => {
    logger.debug('[useSocket] Initializing SocketService')
    const service = new SocketService(url)
    serviceRef.current = service

    // Expose to window (for settings dialog)
    ;(window as any).socket = service.raw

    // Auto-connect
    if (autoConnect) {
      service.connect().catch((err) => {
        logger.error('[useSocket] Auto-connect failed:', err)
      })
    }

    // Cleanup
    return () => {
      logger.debug('[useSocket] Cleaning up SocketService')
      service.disconnect()
      serviceRef.current = null
      ;(window as any).socket = null
    }
  }, [autoConnect, url])

  // Connect
  const connect = useCallback(() => {
    if (serviceRef.current) {
      serviceRef.current.connect().catch((err) => {
        logger.error('[useSocket] Connect failed:', err)
      })
    }
  }, [])

  // Disconnect
  const disconnect = useCallback(() => {
    if (serviceRef.current) {
      serviceRef.current.disconnect()
    }
  }, [])

  // Emit event
  const emit = useCallback(<Event extends keyof SocketEmits>(
    event: Event,
    ...args: Parameters<SocketEmits[Event]>
  ) => {
    if (serviceRef.current?.connected) {
      serviceRef.current.emit(event, ...args)
    } else {
      logger.warn('[useSocket] Cannot emit - not connected:', event)
    }
  }, [])

  const isConnected = useConnectionStore((state) => state.status === 'connected')

  return {
    socket: serviceRef.current,
    isConnected,
    connect,
    disconnect,
    emit,
  }
}

/**
 * Hook for registering Socket event handlers
 */
export function useSocketEvent<Event extends keyof SocketEvents>(
  socket: SocketService | null,
  event: Event,
  callback: SocketEvents[Event],
  deps: React.DependencyList = []
) {
  useEffect(() => {
    if (!socket || !callback) {
      return
    }

    socket.on(event, callback)

    return () => {
      socket.off(event, callback)
    }
  }, [socket, event, callback, ...deps])
}
