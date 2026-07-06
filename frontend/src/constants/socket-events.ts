/**
 * Socket.IO 事件常量定义
 *
 * 单一真相源：config/socket-events.json
 * 本文件从 JSON 生成 TypeScript 类型，提供类型安全
 */

import events from '../../../config/socket-events.json'

// 从 JSON 推断类型
type EventConfig = {
  name: string
  payload: Record<string, unknown>
}

type ModuleEvents = Record<string, EventConfig>

type SocketEventsConfig = Record<string, ModuleEvents>

// 类型断言
const socketEvents = events as SocketEventsConfig

/**
 * 事件常量 - 用于 socket.emit() 和 socket.on()
 *
 * 使用示例：
 * ```typescript
 * import { Events } from '@/constants/socket-events'
 *
 * // 发送事件
 * socket.emit(Events.CHAT.TEXT, { text: 'hello' })
 *
 * // 接收事件
 * socket.on(Events.CHAT.SENTENCE, (data) => { ... })
 * ```
 */
export const Events = {
  CHAT: {
    TEXT: socketEvents.chat.text.name,
    AUDIO: socketEvents.chat.audio.name,
    AUDIO_END: socketEvents.chat.audio_end.name,
    INTERRUPT: socketEvents.chat.interrupt.name,
    SENTENCE: socketEvents.chat.sentence.name,
    CONTROL: socketEvents.chat.control.name,
    TRANSCRIPT: socketEvents.chat.transcript.name,
    STOP_AUDIO: socketEvents.chat.stop_audio.name,
    AUDIO_WITH_EXPRESSION: socketEvents.chat.audio_with_expression.name,
    SUBTITLE_TRANSLATION: socketEvents.chat.subtitle_translation.name,
    LIVE2D_ACTION: socketEvents.chat.live2d_action.name,
    EXPRESSION: socketEvents.chat.expression.name,
  },
  HISTORY: {
    LIST: socketEvents.history.list.name,
    FETCH: socketEvents.history.fetch.name,
    CLEAR: socketEvents.history.clear.name,
    CREATE: socketEvents.history.create.name,
  },
  CONFIG: {
    SWITCH: socketEvents.config.switch.name,
    LOG_LEVEL: socketEvents.config.log_level.name,
    GET: socketEvents.config.get.name,
    SWITCHED: socketEvents.config.switched.name,
    LOG_LEVEL_CHANGED: socketEvents.config.log_level_changed.name,
    DATA: socketEvents.config.data.name,
    HEARTBEAT_ACK: socketEvents.config.heartbeat_ack.name,
  },
  SYSTEM: {
    HEARTBEAT: socketEvents.system.heartbeat.name,
    CONNECTION_ESTABLISHED: socketEvents.system.connection_established.name,
    MODEL_STATUS: socketEvents.system.model_status.name,
    ERROR: socketEvents.system.error.name,
  },
  DESKTOP: {
    REGISTER: socketEvents.desktop.register.name,
    LIVE2D_ACTION: socketEvents.desktop.live2d_action.name,
    CHAT_MESSAGE: socketEvents.desktop.chat_message.name,
    VOICE_START: socketEvents.desktop.voice_start.name,
    VOICE_STOP: socketEvents.desktop.voice_stop.name,
    REGISTERED: socketEvents.desktop.registered.name,
    ACTION_QUEUED: socketEvents.desktop.action_queued.name,
    VOICE_STARTED: socketEvents.desktop.voice_started.name,
    VOICE_STOPPED: socketEvents.desktop.voice_stopped.name,
  },
  BILIBILI: {
    CONNECT: socketEvents.bilibili.connect.name,
    DISCONNECT: socketEvents.bilibili.disconnect.name,
    UPDATE_ROOM: socketEvents.bilibili.update_room.name,
    DANMAKU: socketEvents.bilibili.danmaku.name,
    DANMAKU_STATUS: socketEvents.bilibili.danmaku_status.name,
    DANMAKU_AI_REPLY: socketEvents.bilibili.danmaku_ai_reply.name,
  },
  MINECRAFT: {
    START: socketEvents.minecraft.start.name,
    STOP: socketEvents.minecraft.stop.name,
    STATUS: socketEvents.minecraft.status.name,
    SPECTATE: socketEvents.minecraft.spectate.name,
    COMMAND: socketEvents.minecraft.command.name,
    VIEWER_STATUS: socketEvents.minecraft.viewer_status.name,
    BOT_STATE: socketEvents.minecraft.bot_state.name,
    COMMAND_RESULT: socketEvents.minecraft.command_result.name,
  },
  TRANSLATION: {
    CONFIGURE: socketEvents.translation.configure.name,
    STATUS: socketEvents.translation.status.name,
  },
  PERSONA: {
    LIST: socketEvents.persona.list.name,
    SET: socketEvents.persona.set.name,
    SET_MODE: socketEvents.persona.set_mode.name,
    UPDATED: socketEvents.persona.updated.name,
    PERSONALITY_UPDATED: socketEvents.persona.personality_updated.name,
  },
  MEMORY: {
    ORGANIZE: socketEvents.memory.organize.name,
    LIST_PAGES: socketEvents.memory.list_pages.name,
    ORGANIZE_PROGRESS: socketEvents.memory.organize_progress.name,
    ORGANIZE_RESULT: socketEvents.memory.organize_result.name,
  },
  SING: {
    PROCESS: socketEvents.sing.process.name,
    CONFIRM_LYRICS: socketEvents.sing.confirm_lyrics.name,
    CANCEL: socketEvents.sing.cancel.name,
    SUBTITLE_SYNC: socketEvents.sing.subtitle_sync.name,
    PROGRESS: socketEvents.sing.progress.name,
    COMPLETE: socketEvents.sing.complete.name,
    ERROR: socketEvents.sing.error.name,
    LYRICS_READY: socketEvents.sing.lyrics_ready.name,
    SUBTITLE_LINE: socketEvents.sing.subtitle_line.name,
  },
  MEME: {
    ADD: socketEvents.meme.add.name,
    LIST: socketEvents.meme.list.name,
    REVIEW: socketEvents.meme.review.name,
    DATASET: socketEvents.meme.dataset.name,
    COLLECT: socketEvents.meme.collect.name,
  },
} as const

/**
 * Payload 类型定义
 */
export interface ChatTextPayload {
  text: string
  user_id?: string
  from_name?: string
}

export interface ChatAudioPayload {
  audio: number[]
}

export interface ChatSentencePayload {
  text: string
  seq: number
  lang: string
  is_complete?: boolean
}

export interface ChatTranscriptPayload {
  text: string
  is_final: boolean
}

export interface SingProcessPayload {
  url?: string
  file?: string
  auto_confirm?: boolean
}

export interface SingCompletePayload {
  audio_url: string
  subtitle_url: string
  tts_audio_url: string
  vocals_url: string
  video_title: string
  duration: number
  lyrics: Array<{ text: string; translation: string; start_ms: number; end_ms: number }>
  volumes: number[]
}

export interface PersonaSetPayload {
  persona_name: string
}

export interface PersonaSetModePayload {
  mode: string
}

export interface MemoryOrganizeProgressPayload {
  text: string
  progress: number
}

export interface MemoryOrganizeResultPayload {
  status: string
  message: string
}

export interface BilibiliConnectPayload {
  room_id: number
}

export interface MinecraftStatusPayload {
  connected: boolean
  username?: string
  error?: string
}

export interface SystemModelStatusPayload {
  model_name: string
  status: string
  progress: number
}

export interface SystemErrorPayload {
  type: string
  message: string
}

/**
 * 导出原始 JSON 配置（用于验证脚本）
 */
export { socketEvents }
