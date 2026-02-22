/**
 * useConversation Hook
 * React 状态包装器，使用 ConversationService
 *
 * 职责：
 * - 管理 React state
 * - 将 ConversationService 事件映射到 React state
 * - 提供统一的组件 API
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import { useConversationStore } from '../stores/conversationStore'
import { useAudioPlayer } from '@/features/audio/hooks'
import { useConnection } from './useConnection'
import { useMessaging } from './useMessaging'
import { useAudioInteraction } from './useAudioInteraction'
import { getConversationService } from '@/features/conversation/services'
import { logger } from '@/shared/utils/logger'
import type { UseConversationReturn, ConversationOptions } from './types'
import type { SocketService } from '@/features/connection/services/SocketService'

/**
 * Hook for conversation functionality
 *
 * @param options - Configuration options
 * @returns Conversation state and methods
 *
 * @example
 * ```tsx
 * function ChatPanel() {
 *   const { isConnected, messages, sendText, startRecording } = useConversation()
 *   return <div>...</div>
 * }
 * ```
 */
export function useConversation(options: ConversationOptions = {}): UseConversationReturn {
  const { autoConnect = true, onStatusChange, onError } = options

  // Stores
  const conversationState = useConversationStore()

  // Expression state (not in store to avoid persistence)
  const [expression, setExpressionState] = useState('idle')

  // Refs for callbacks (avoid stale closures)
  const onStatusChangeRef = useRef(onStatusChange)
  const onErrorRef = useRef(onError)

  // Update refs when callbacks change
  useEffect(() => {
    onStatusChangeRef.current = onStatusChange
    onErrorRef.current = onError
  })

  // ============ Connection Module ============
  const { socket, isConnected, connect, disconnect } = useConnection({
    autoConnect,
    onConnected: () => {
      conversationState.setError(null)
    },
    onDisconnected: () => {
      conversationState.setStatus('idle')
    },
    onError: (error) => {
      conversationState.setError(error)
    },
  })

  // ============ Conversation Service ============
  // 使用单例模式，避免多个组件创建多个实例导致事件监听器重复注册
  const serviceRef = useRef<ReturnType<typeof getConversationService> | null>(null)

  // 初始化 ConversationService（单例）
  useEffect(() => {
    if (!socket) return

    // 获取单例实例
    const service = getConversationService()
    serviceRef.current = service

    // 初始化服务（幂等操作）
    service.initialize(socket)
    logger.debug('[useConversation] ConversationService 初始化完成（单例）')

    // 监听服务事件
    const unsubscribeStatusChange = service.on('status:change', (status) => {
      onStatusChangeRef.current?.(status)
    })

    const unsubscribeError = service.on('error', (error) => {
      onErrorRef.current?.(error)
    })

    const unsubscribeExpression = service.on('expression', (expr) => {
      setExpressionState(expr)
    })

    // 清理
    return () => {
      unsubscribeStatusChange()
      unsubscribeError()
      unsubscribeExpression()
    }
  }, [socket])

  // ============ Audio Player Module ============
  const { playAudio } = useAudioPlayer(
    () => {
      conversationState.setStatus('speaking')
      onStatusChangeRef.current?.('speaking')
    },
    () => {
      conversationState.setStatus('idle')
      onStatusChangeRef.current?.('idle')
    }
  )

  // ============ Audio Interaction Module ============
  const audioInteraction = useAudioInteraction(socket, {
    onStatusChange,
    onError,
  })

  // ============ Messaging Module ============
  const messaging = useMessaging(socket, {
    onStatusChange,
    onError,
  })

  // ============ Return API ============

  // 确保 service 存在（单例在 useEffect 中初始化）
  const service = serviceRef.current

  return {
    // Connection state
    isConnected,

    // Conversation state
    status: conversationState.status,
    messages: conversationState.messages,
    currentResponse: conversationState.currentResponse,
    isTyping: conversationState.isTyping,
    error: conversationState.error,
    expression,

    // Methods - 使用 service 的方法（单例，确保事件监听正常）
    connect,
    disconnect,
    sendText: (text: string) => service?.sendText(text),
    clearHistory: () => service?.clearHistory(),
    startRecording: audioInteraction.startRecording,
    stopRecording: audioInteraction.stopRecording,
    cancelRecording: audioInteraction.cancelRecording,
    interrupt: audioInteraction.interrupt,
    setExpression: setExpressionState,
  }
}

// Re-export types for convenience
export type { UseConversationReturn, ConversationOptions }
