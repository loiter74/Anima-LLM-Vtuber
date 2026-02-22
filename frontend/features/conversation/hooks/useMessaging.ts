/**
 * useMessaging Hook
 * 消息发送功能
 */

import { useEffect, useRef, useCallback } from 'react'
import { MessagingService } from '@/features/conversation/services'
import type { SocketService } from '@/features/connection/services/SocketService'
import type { UseMessagingOptions, UseMessagingReturn } from './types'

export function useMessaging(
  socket: SocketService | null,
  options: UseMessagingOptions = {}
): UseMessagingReturn {
  const { onStatusChange, onError } = options

  // Service 实例（只创建一次）
  const serviceRef = useRef<MessagingService | null>(null)

  // 初始化 service
  useEffect(() => {
    if (!socket) return
    if (serviceRef.current) return

    serviceRef.current = new MessagingService()
    serviceRef.current.setSocket(socket)

    // 监听服务事件
    serviceRef.current.on('response:start', () => {
      onStatusChange?.('processing')
    })

    serviceRef.current.on('response:timeout', () => {
      onError?.('响应超时，请重试')
    })
  }, [socket, onStatusChange, onError])

  // Send text message
  const sendText = useCallback(
    (text: string) => {
      serviceRef.current?.sendText(text)
    },
    []
  )

  // Clear history
  const clearHistory = useCallback(() => {
    serviceRef.current?.clearHistory()
  }, [])

  return {
    sendText,
    clearHistory,
  }
}
