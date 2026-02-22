/**
 * useSocket Hook
 * Socket.IO 连接管理（全局单例模式）
 */

import { useEffect, useCallback } from 'react'
import { SocketService } from '../services/SocketService'
import { useConnectionStore } from '../stores/connectionStore'
import type { SocketEvents, SocketEmits } from '../types'

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

// 全局单例
let globalSocketService: SocketService | null = null
let isInitialized = false

/**
 * Hook for Socket.IO connection management
 */
export function useSocket(options: UseSocketOptions = {}): UseSocketReturn {
  const { autoConnect = true, url } = options

  // 初始化 socket（只执行一次）
  useEffect(() => {
    if (isInitialized) {
      return
    }

    isInitialized = true
    globalSocketService = new SocketService(url)

    // 暴露到 window（用于设置对话框）
    ;(window as any).socket = globalSocketService.raw

    // 自动连接
    if (autoConnect) {
      globalSocketService.connect().catch((err) => {
        console.error('[useSocket] Auto-connect failed:', err)
      })
    }

    // 清理函数 - 不断开全局 socket
    return () => {
      // Keep global socket alive
    }
  }, [])

  const connect = useCallback(() => {
    globalSocketService?.connect().catch((err) => {
      console.error('[useSocket] Connect failed:', err)
    })
  }, [])

  const disconnect = useCallback(() => {
    globalSocketService?.disconnect()
  }, [])

  const emit = useCallback(<Event extends keyof SocketEmits>(
    event: Event,
    ...args: Parameters<SocketEmits[Event]>
  ) => {
    if (globalSocketService?.connected) {
      globalSocketService.emit(event, ...args)
    }
  }, [])

  const isConnected = useConnectionStore((state) => state.status === 'connected')

  return {
    socket: globalSocketService,
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
    if (!socket || !callback) return

    socket.on(event, callback)

    return () => {
      socket.off(event, callback)
    }
  }, [socket, event, callback, ...deps])
}
