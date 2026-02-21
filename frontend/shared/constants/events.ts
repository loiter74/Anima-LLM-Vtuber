/**
 * Socket.IO Event Constants
 * Centralized event name definitions
 */

export const SOCKET_EVENTS = {
  // Connection events
  CONNECTION_ESTABLISHED: 'connection-established',
  CONNECT: 'connect',
  DISCONNECT: 'disconnect',
  CONNECT_ERROR: 'connect_error',

  // Message events
  TEXT: 'text',
  AUDIO: 'audio',
  TRANSCRIPT: 'transcript',

  // Control events
  CONTROL: 'control',
  INTERRUPT: 'interrupt',
  INTERRUPTED: 'interrupted',

  // Error events
  ERROR: 'error',

  // Client emit events
  TEXT_INPUT: 'text_input',
  MIC_AUDIO_DATA: 'mic_audio_data',
  RAW_AUDIO_DATA: 'raw_audio_data',
  MIC_AUDIO_END: 'mic_audio_end',
  INTERRUPT_SIGNAL: 'interrupt_signal',
  SET_LOG_LEVEL: 'set_log_level',
  CLEAR_HISTORY: 'clear_history',
} as const

export const CONTROL_SIGNALS = {
  START_MIC: 'start-mic',
  INTERRUPT: 'interrupt',
  INTERRUPTED: 'interrupted',
  MIC_AUDIO_END: 'mic-audio-end',
  NO_AUDIO_DATA: 'no-audio-data',
  CONVERSATION_START: 'conversation-start',
  CONVERSATION_END: 'conversation-end',
} as const
