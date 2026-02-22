/**
 * Conversation Hook Types
 * Hook 层专用类型定义
 *
 * 职责划分：
 * - features/conversation/types/ → 数据模型（Message, ConversationStatus）
 * - features/conversation/hooks/types.ts → UI 配置（仅用于 React Hook）
 */

import type { ConversationStatus } from '../types'
import type { SocketService } from '@/features/connection/services/SocketService'

// ============ Connection Types ============

export interface UseConnectionOptions {
  autoConnect?: boolean
  onConnected?: () => void
  onDisconnected?: () => void
  onError?: (error: string) => void
}

export interface UseConnectionReturn {
  socket: SocketService | null
  isConnected: boolean
  connect: () => void
  disconnect: () => void
}

// ============ Messaging Types ============

export interface UseMessagingOptions {
  onStatusChange?: (status: ConversationStatus) => void
  onError?: (error: string) => void
}

export interface UseMessagingReturn {
  sendText: (text: string) => void
  clearHistory: () => void
}

// ============ Audio Interaction Types ============

export interface UseAudioInteractionOptions {
  onStatusChange?: (status: ConversationStatus) => void
  onError?: (error: string) => void
}

export interface UseAudioInteractionReturn {
  isRecording: boolean
  startRecording: () => Promise<void>
  stopRecording: () => void
  cancelRecording: () => void
  interrupt: () => void
  playAudio: (base64: string, format?: string) => void
}

// ============ Main Conversation Types ============

export interface ConversationOptions {
  autoConnect?: boolean
  onStatusChange?: (status: ConversationStatus) => void
  onError?: (error: string) => void
}

export interface UseConversationReturn {
  // Connection state
  isConnected: boolean

  // Conversation state
  status: ConversationStatus
  messages: import('../types').Message[]
  currentResponse: string
  isTyping: boolean
  error: string | null
  expression: string

  // Methods
  connect: () => void
  disconnect: () => void
  sendText: (text: string) => void
  startRecording: () => Promise<void>
  stopRecording: () => void
  cancelRecording: () => void
  interrupt: () => void
  clearHistory: () => void
  setExpression: (expression: string) => void
}
