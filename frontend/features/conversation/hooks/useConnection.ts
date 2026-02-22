/**
 * useConnection Hook
 * 连接状态管理
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useSocket } from '@/features/connection/hooks/useSocket'
import { ConnectionService, type ConnectionState } from '@/features/conversation/services'
import type { UseConnectionOptions, UseConnectionReturn } from './types'

export function useConnection(options: UseConnectionOptions = {}): UseConnectionReturn {
  const { autoConnect = true, onConnected, onDisconnected, onError } = options

  // 使用 ref 存储 callbacks，避免依赖变化
  const onConnectedRef = useRef(onConnected)
  const onDisconnectedRef = useRef(onDisconnected)
  const onErrorRef = useRef(onError)

  // 更新 refs
  useEffect(() => {
    onConnectedRef.current = onConnected
    onDisconnectedRef.current = onDisconnected
    onErrorRef.current = onError
  })

  // Socket connection（由 useSocket 统一管理）
  const { socket, connect: socketConnect, disconnect: socketDisconnect } = useSocket({
    autoConnect,
  })

  // Service 实例（只创建一次）
  const serviceRef = useRef<ConnectionService | null>(null)

  // React state
  const [connectionState, setConnectionState] = useState<ConnectionState>({
    status: 'disconnected',
    error: null,
  })

  // 初始化 service
  useEffect(() => {
    if (!socket) return

    if (serviceRef.current) return

    serviceRef.current = new ConnectionService()
    serviceRef.current.setSocket(socket)

    const service = serviceRef.current

    // 监听服务事件
    const unsubscribers = [
      service.on('status:change', (state) => {
        setConnectionState(state)

        if (state.status === 'connected') {
          onConnectedRef.current?.()
        } else if (state.status === 'disconnected') {
          onDisconnectedRef.current?.()
        }
      }),

      service.on('connected', () => {
        onConnectedRef.current?.()
      }),

      service.on('disconnected', () => {
        onDisconnectedRef.current?.()
      }),

      service.on('error', (error) => {
        onErrorRef.current?.(error)
      }),
    ]

    // 清理
    return () => {
      unsubscribers.forEach(unsub => unsub())
    }
  }, [socket])

  // Connection methods（直接使用 useSocket 的方法）
  const connect = useCallback(() => {
    socketConnect()
  }, [socketConnect])

  const disconnect = useCallback(() => {
    socketDisconnect()
  }, [socketDisconnect])

  return {
    socket,
    isConnected: connectionState.status === 'connected',
    connect,
    disconnect,
  }
}
