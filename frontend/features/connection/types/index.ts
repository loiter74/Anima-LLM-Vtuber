/**
 * Socket.IO Type Definitions
 * Socket.IO 事件类型定义
 */

// Server → Client events
export interface SocketEvents {
  // Built-in Socket.IO events
  connect: () => void
  disconnect: (reason: string) => void
  connect_error: (error: Error) => void

  // Custom events
  'connection-established': (data: ConnectionEstablishedData) => void
  'text': (data: SentenceEvent) => void
  'audio': (data: AudioEvent) => void
  'transcript': (data: TranscriptEvent) => void
  'control': (data: ControlEvent) => void
  'error': (data: ErrorEvent) => void
  'expression': (data: ExpressionEvent) => void
}

// Client → Server events
export interface SocketEmits {
  'text_input': (data: TextInputData) => void
  'mic_audio_data': (data: AudioData) => void
  'raw_audio_data': (data: AudioData) => void
  'mic_audio_end': (data: MicAudioEndData) => void
  'interrupt_signal': (data: InterruptData) => void
  'set_log_level': (data: SetLogLevelData) => void
  'clear_history': () => void
}

// Event data types
export interface ConnectionEstablishedData {
  message: string
  sid: string
}

export interface SentenceEvent {
  type: string
  text: string
  seq: number
}

export interface AudioEvent {
  type: string
  audio_url?: string
  audio_data?: string
  format?: string
  seq?: number
}

export interface TranscriptEvent {
  type: string
  text: string
  is_final?: boolean
}

export interface ControlEvent {
  text: string
  type?: string
}

export interface ErrorEvent {
  type: string
  message: string
}

export interface ExpressionEvent {
  type: string
  expression: string
  timestamp?: number
}

export interface TextInputData {
  text: string
  from_name?: string
}

export interface AudioData {
  audio: number[]
}

export interface MicAudioEndData {
  from_name?: string
}

export interface InterruptData {
  text?: string
}

export interface SetLogLevelData {
  level: string
}
