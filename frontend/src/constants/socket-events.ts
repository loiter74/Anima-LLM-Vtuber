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
  ack?: Record<string, unknown>
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
  TOOL: {
    APPROVAL_REQUIRED: socketEvents.tool.approval_required.name,
    APPROVAL_LIST: socketEvents.tool.approval_list.name,
    APPROVAL_DECIDE: socketEvents.tool.approval_decide.name,
    APPROVAL_RESOLVED: socketEvents.tool.approval_resolved.name,
  },
  TASK: {
    STATUS: socketEvents.task.status.name,
    SNAPSHOT: socketEvents.task.snapshot.name,
  },
  CHAT: {
    TEXT: socketEvents.chat.text.name,
    DEVELOPER_TEXT: socketEvents.chat.developer_text.name,
    SANDBOX_REQUEST: socketEvents.chat.sandbox_request.name,
    SANDBOX_CANCEL: socketEvents.chat.sandbox_cancel.name,
    SANDBOX_CHUNK: socketEvents.chat.sandbox_chunk.name,
    AUDIO: socketEvents.chat.audio.name,
    AUDIO_END: socketEvents.chat.audio_end.name,
    INTERRUPT: socketEvents.chat.interrupt.name,
    SENTENCE: socketEvents.chat.sentence.name,
    CONTROL: socketEvents.chat.control.name,
    TRANSCRIPT: socketEvents.chat.transcript.name,
    STOP_AUDIO: socketEvents.chat.stop_audio.name,
    AUDIO_WITH_EXPRESSION: socketEvents.chat.audio_with_expression.name,
    AUDIO_STREAM_START: socketEvents.chat.audio_stream_start.name,
    AUDIO_STREAM_CHUNK: socketEvents.chat.audio_stream_chunk.name,
    AUDIO_STREAM_END: socketEvents.chat.audio_stream_end.name,
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
    LIVE_EVENT: socketEvents.bilibili.live_event.name,
    DANMAKU_AI_REPLY: socketEvents.bilibili.danmaku_ai_reply.name,
  },
  MINECRAFT: {
    CONNECT: socketEvents.minecraft.connect.name,
    STATUS: socketEvents.minecraft.status.name,
    DISCONNECT: socketEvents.minecraft.disconnect.name,
    SHUTDOWN: socketEvents.minecraft.shutdown.name,
    REATTACH_VIEWER: socketEvents.minecraft.reattach_viewer.name,
    VIEWER_STATUS: socketEvents.minecraft.viewer_status.name,
    COMMAND_TRANSITION: socketEvents.minecraft.command_transition.name,
    SKILL_TRUST: socketEvents.minecraft.skill_trust.name,
    MISSION_PROJECTION: socketEvents.minecraft.mission_projection.name,
    OBJECTIVE_PROJECTION: socketEvents.minecraft.objective_projection.name,
    PROPOSAL_PROJECTION: socketEvents.minecraft.proposal_projection.name,
    DISCOVERY_PROJECTION: socketEvents.minecraft.discovery_projection.name,
    SKILL_VALIDATION: socketEvents.minecraft.skill_validation.name,
    ADVANCEMENT_PROJECTION: socketEvents.minecraft.advancement_projection.name,
    STAGE_PROJECTION: socketEvents.minecraft.stage_projection.name,
    ACTIVITY_PROJECTION: socketEvents.minecraft.activity_projection.name,
    BOT_STATE: socketEvents.minecraft.bot_state.name,
  },
  LIVESTREAM: {
    NARRATION_STATE: socketEvents.livestream.narration_state.name,
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
    LIST: socketEvents.memory.list.name,
    GET: socketEvents.memory.get.name,
    SEARCH: socketEvents.memory.search.name,
    PIN: socketEvents.memory.pin.name,
    FORGET: socketEvents.memory.forget.name,
    CHANGE: socketEvents.memory.change.name,
    JOB: socketEvents.memory.job.name,
    CHANGED: socketEvents.memory.changed.name,
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

export interface SingCompletePayload {
  task_id: string
  audio_url: string
  subtitle_url?: string
  tts_audio_url?: string
  vocals_url?: string
  original_url?: string
  video_title?: string
  duration: number
  voice_conversion_applied: boolean
  voice_provider: string
  voice_model: string
  voice_revision: string
  voice_name: string
  lyrics?: Array<{ text: string; translation: string; start_ms: number; end_ms: number }>
  volumes?: number[]
}

export type LivestreamState =
  'stopped' | 'connecting' | 'prelive' | 'live' | 'reconnecting' | 'stopping' | 'error'

export interface BilibiliCommandAck {
  accepted: boolean
  state: LivestreamState
  error_code: string | null
  message: string
}

export interface BilibiliStatusPayload {
  state: LivestreamState
  connected: boolean
  room_id: number | null
  desired_room_id: number | null
  retry_count: number
  error_code: string | null
  generation_id: number
  message: string
  updated_at: number
}

/**
 * 导出原始 JSON 配置（用于验证脚本）
 */
export { socketEvents }
