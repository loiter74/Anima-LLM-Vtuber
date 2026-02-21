/**
 * Conversation Type Definitions
 * Defines all conversation-related types
 */

export type ConversationStatus =
  | "idle"           // 空闲
  | "listening"      // 正在监听用户输入
  | "processing"     // 正在处理
  | "speaking"       // AI 正在说话
  | "interrupted"    // 被打断
  | "error"          // 错误

export interface Message {
  id: string
  sender: "user" | "ai"
  text: string
  time: string
  status?: "pending" | "sent" | "error"
}

export interface ConversationState {
  status: ConversationStatus
  messages: Message[]
  currentResponse: string
  isTyping: boolean
  error: string | null
}

export interface ConversationActions {
  setStatus: (status: ConversationStatus) => void
  addMessage: (sender: "user" | "ai", text: string) => void
  clearMessages: () => void
  setCurrentResponse: (response: string) => void
  appendToResponse: (text: string) => void
  finishResponse: () => void
  setError: (error: string | null) => void
  setTyping: (typing: boolean) => void
}

export interface ConversationOptions {
  autoConnect?: boolean
  onStatusChange?: (status: ConversationStatus) => void
  onError?: (error: string) => void
}
