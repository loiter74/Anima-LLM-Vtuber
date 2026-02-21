/**
 * Audio Type Definitions
 * Defines all audio-related types
 */

export type AudioRecorderState = "idle" | "recording" | "stopped" | "error"
export type AudioPlayerState = "idle" | "playing" | "stopped" | "error"

export interface AudioRecorderOptions {
  sampleRate?: number
  channelCount?: number
  echoCancellation?: boolean
  noiseSuppression?: boolean
  autoGainControl?: boolean
  gain?: number
}

export interface AudioPlayerOptions {
  onPlayStart?: () => void
  onPlayEnd?: () => void
  onError?: (error: Error) => void
}

export interface AudioDataCallback {
  (pcmData: Int16Array): void
}

export interface AudioRecorderStateData {
  isRecording: boolean
  volumeLevel: number
  error: string | null
}

export interface AudioRecorderActions {
  setRecording: (recording: boolean) => void
  setVolumeLevel: (level: number) => void
  setError: (error: string | null) => void
}

export interface AudioPlayerStateData {
  isPlaying: boolean
  currentUrl: string | null
  error: string | null
}

export interface AudioPlayerActions {
  setPlaying: (playing: boolean) => void
  setCurrentUrl: (url: string | null) => void
  setError: (error: string | null) => void
}
