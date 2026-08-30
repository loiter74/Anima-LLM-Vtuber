import events from '../../../../config/socket-events.json'

export const PublicLiveEvents = {
  ACTIVITY_PROJECTION: events.minecraft.activity_projection.name,
  NARRATION_STATE: events.livestream.narration_state.name,
} as const

export type ConnectionStatus = 'connected' | 'disconnected' | 'connecting' | 'error'

export type CommandTaskStatus =
  'accepted' | 'processing' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted'

export interface CommandTaskSnapshot {
  kind: string
  task_id: string
  status: CommandTaskStatus
  progress: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error: { code: string; message: string } | null
  reused: boolean
  created_at: number
  updated_at: number
}

export interface ChatIdentity {
  message_id: string
  conversation_id: string
  task_id: string
  turn_id: string
}

export interface ChatCommandPayload extends ChatIdentity {
  text: string
  source: 'text'
  is_inspection: false
  is_acceptance: boolean
  user_id?: string
  from_name?: string
}

/**
 * Payload for the `sentence` socket event (LLM streaming response).
 * Extended with optional translation fields for bilingual subtitle support.
 */
export interface SentenceEvent extends ChatIdentity {
  text: string
  seq: number
  is_complete?: boolean
  /** Original language code (e.g. "zh", "en") */
  lang?: string
  /** Translated text in the target language */
  translation?: string
  /** Target language code (e.g. "en", "ja") */
  target_lang?: string
  /** Optional workflow/effect metadata for expression effects. */
  metadata?: Record<string, unknown>
}

/** Payload for `chat:subtitle_translation` server-to-client event */
export interface SubtitleTranslationEvent extends ChatIdentity {
  translation: string
  target_lang?: string
}

export interface ChatControlEvent extends ChatIdentity {
  signal?: 'conversation-start' | 'conversation-end'
  type?: string
  text?: string
  status?: 'degraded'
}

export interface ParameterTimelineParameter {
  name: string
  value: number
  duration: number
}

export interface ParameterTimelineFrame {
  timestamp: number
  parameters: ParameterTimelineParameter[]
}

export interface ParameterTimeline {
  frames: ParameterTimelineFrame[]
  total_duration?: number
}

export type {
  Live2DPerformanceAccent,
  Live2DPerformanceBase,
  Live2DPerformancePlanV1,
} from '@/shared/live2d/performanceContract'
import type { Live2DPerformancePlanV1 } from '@/shared/live2d/performanceContract'

export interface AudioWithExpressionEvent extends ChatIdentity {
  audio_data: string
  format: string
  volumes?: number[]
  use_parameter_mapping?: boolean
  expressions?: ParameterTimeline
  return_to_idle?: boolean
  performance?: Live2DPerformancePlanV1
}

export type ChatEmotion = 'neutral' | 'happy' | 'sad' | 'angry' | 'surprised' | 'thinking'

export interface AudioStreamStartEvent extends ChatIdentity {
  stream_id: string
  format: 'pcm_s16le'
  sample_rate: 24000
  channels: 1
  emotion: ChatEmotion
  performance?: Live2DPerformancePlanV1
}

export interface AudioStreamChunkEvent extends ChatIdentity {
  stream_id: string
  sequence: number
  audio_data: string
}

export interface AudioStreamEndEvent extends ChatIdentity {
  stream_id: string
  final_sequence: number
  status: 'completed' | 'failed' | 'cancelled'
  reason?: 'timeout' | 'provider_error' | 'cancelled'
}

export type MinecraftPublicActivityOutcome =
  'active' | 'succeeded' | 'failed' | 'cancelled' | 'blocked'

export type MinecraftPublicActivityPhase =
  'planning' | 'observing' | 'committed' | 'acting' | 'checking' | 'recovering' | 'finished'

export type MinecraftPublicActivityIntent =
  | 'acquire'
  | 'craft'
  | 'build'
  | 'travel'
  | 'combat'
  | 'survive'
  | 'learn'
  | 'discover'
  | 'interact'

export type MinecraftPublicActivityFocusKind =
  'item' | 'entity' | 'place' | 'structure' | 'condition'

export type MinecraftPublicActivityProgressUnit = 'objectives' | 'items' | 'blocks' | 'actions'

export interface MinecraftPublicActivityFocus {
  kind: MinecraftPublicActivityFocusKind
  label: string
}

export interface MinecraftPublicActivityProgress {
  current: number
  total: number
  unit: MinecraftPublicActivityProgressUnit
}

export interface MinecraftPublicActivityPayload {
  phase: MinecraftPublicActivityPhase
  intent?: MinecraftPublicActivityIntent
  focus?: MinecraftPublicActivityFocus
  progress?: MinecraftPublicActivityProgress
  outcome: MinecraftPublicActivityOutcome
}

export interface MinecraftActivityProjectionEvent {
  schema_version: '1'
  event: 'minecraft.activity.projection'
  event_id: string
  projection_kind: 'activity'
  projection_version: number
  occurred_at_ms: number
  mission_id?: string
  entity_id: 'minecraft'
  payload: MinecraftPublicActivityPayload
}

export type LivestreamNarrationSpeechState =
  'none' | 'queued' | 'speaking' | 'completed' | 'cancelled'

export type LivestreamNarrationEmotion = 'thinking' | 'confident' | 'focused' | 'alert' | 'relieved'

export interface LivestreamNarrationStateEvent {
  schema_version: '1'
  cue_id: string
  source_event_id: string
  task_id?: string
  phase: MinecraftPublicActivityPhase
  visual_text: string
  emotion: LivestreamNarrationEmotion
  speech_state: LivestreamNarrationSpeechState
  occurred_at_ms: number
}

export interface ChatErrorEvent extends ChatIdentity {
  type: 'validation_error' | 'processing_error' | 'timeout' | 'interrupted' | 'internal_error'
  message: string
  component: string
  phase: string
  retryable: boolean
  terminal: boolean
}

export interface SandboxHistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface SandboxRequestEvent extends ChatIdentity {
  text: string
  history: SandboxHistoryMessage[]
}

export interface SandboxChunkEvent extends ChatIdentity {
  text: string
  seq: number
  provider: string
  model?: string | null
  is_complete?: boolean
  error_code?: string | null
}
