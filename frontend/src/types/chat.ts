export type MessageRole = 'user' | 'assistant' | 'system'
export type MessageStatus = 'streaming' | 'complete'

export interface ChatMessage {
  id: string
  role: MessageRole
  text: string
  timestamp: number
  status: MessageStatus
  source?: 'text' | 'voice'
  message_id?: ChatIdentity['message_id']
  conversation_id?: ChatIdentity['conversation_id']
  task_id?: ChatIdentity['task_id']
  turn_id?: ChatIdentity['turn_id']
}

export interface LlmChunk {
  text: string
  seq: number
  is_complete: boolean
}

export interface Transcript {
  text: string
  is_final: boolean
}

/** Bilibili danmaku message from backend */
export interface DanmakuItem {
  text: string
  user_name: string
  user_id: number
  timestamp: number
}

/** Status of Bilibili connection */
export interface DanmakuStatus {
  connected: boolean
  message?: string
}

/** AI reply to a danmaku */
export interface DanmakuReply {
  danmaku_text: string
  reply_text: string
  user_name: string
  character_name: string
  timestamp: number
}
import type { ChatIdentity } from './socket-events'
