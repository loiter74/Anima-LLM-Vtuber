export type ConnectionStatus = 'connected' | 'disconnected' | 'connecting' | 'error'

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

export interface AudioWithExpressionEvent extends ChatIdentity {
  audio_data: string
  format: string
  volumes?: number[]
  use_parameter_mapping?: boolean
  expressions?: ParameterTimeline
  return_to_idle?: boolean
}

export type ChatEmotion = 'neutral' | 'happy' | 'sad' | 'angry' | 'surprised' | 'thinking'

export interface AudioStreamStartEvent extends ChatIdentity {
  stream_id: string
  format: 'pcm_s16le'
  sample_rate: 24000
  channels: 1
  emotion: ChatEmotion
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

export interface ChatErrorEvent extends ChatIdentity {
  type: 'validation_error' | 'processing_error' | 'timeout' | 'interrupted' | 'internal_error'
  message: string
  component: string
  phase: string
  retryable: boolean
  terminal: boolean
}
