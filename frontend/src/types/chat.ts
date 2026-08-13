import type { ChatIdentity } from './socket-events'

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

export interface Transcript {
  text: string
  is_final: boolean
}

/** Bilibili danmaku message from backend */
export interface DanmakuItem {
  source_message_id?: string
  text: string
  user_name: string
  user_id: number
  timestamp: number
  is_gift?: boolean
  is_super_chat?: boolean
  meta?: Record<string, unknown>
}

/** Status of Bilibili connection */
export interface DanmakuStatus {
  state: 'stopped' | 'connecting' | 'live' | 'reconnecting' | 'stopping' | 'error'
  connected: boolean
  room_id: number | null
  desired_room_id: number | null
  retry_count: number
  error_code: string | null
  generation_id: number
  message: string
  updated_at: number
}

/** AI reply to a danmaku */
export interface DanmakuReply {
  danmaku_text: string
  reply_text: string
  user_name: string
  character_name: string
  timestamp: number
}
