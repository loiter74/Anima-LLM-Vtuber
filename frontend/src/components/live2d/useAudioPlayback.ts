import type {
  AudioStreamChunkEvent,
  AudioStreamEndEvent,
  AudioStreamStartEvent,
  ParameterTimeline,
} from '@/types/socket-events'
import { startLipSync, stopLipSync, type MouthTarget } from './useLipSync'
import { setExpression } from './useLive2DModel'
import {
  endPcmAudioStream,
  pushPcmAudioStreamChunk,
  startPcmAudioStream,
  stopPcmAudioStream,
  unlockPcmAudioPlayback,
} from './usePcmStreamPlayback'

// ===== Audio State =====

const SILENT_AUDIO_DATA_URL =
  'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACAgICA'

let currentAudio: HTMLAudioElement | null = null
let currentBlobUrl: string | null = null
let audioUnlocked = false
let unlockPending = false
let currentLifecycle: AudioPlaybackLifecycle | null = null

// ===== Audio Playback =====

function cleanup(): void {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio.onended = null
    currentAudio.removeAttribute('src')
    currentAudio.load()
  }
  if (currentBlobUrl) {
    URL.revokeObjectURL(currentBlobUrl)
    currentBlobUrl = null
  }
}

function getAudioElement(): HTMLAudioElement {
  if (!currentAudio) currentAudio = new Audio()
  return currentAudio
}

/**
 * Prime the persistent chat audio element while a trusted user gesture is
 * active. TTS arrives asynchronously, after the browser's transient autoplay
 * permission has expired, so the later response must reuse this element.
 */
export function unlockAudioPlayback(): void {
  unlockPcmAudioPlayback()
  if (audioUnlocked || unlockPending || currentBlobUrl) return

  const audio = getAudioElement()
  audio.src = SILENT_AUDIO_DATA_URL
  unlockPending = true

  audio
    .play()
    .then(() => {
      audioUnlocked = true
      if (!currentBlobUrl && audio.src === SILENT_AUDIO_DATA_URL) {
        audio.pause()
        audio.removeAttribute('src')
        audio.load()
      }
    })
    .catch((error: unknown) => {
      console.warn('[audio] Unable to unlock chat audio playback', error)
    })
    .finally(() => {
      unlockPending = false
    })
}

export interface AudioPlaybackPayload {
  audio_data?: string
  audio_url?: string
  format?: string
  volumes?: number[]
  expressions?: ParameterTimeline
  return_to_idle?: boolean
}

export interface AudioPlaybackLifecycle {
  onStart?: () => void
  onComplete?: () => void
  onCancel?: () => void
}

export function playAudio(
  data: AudioPlaybackPayload,
  lifecycle?: AudioPlaybackLifecycle,
  mouthTarget?: MouthTarget,
): void {
  if (!data?.audio_data && !data?.audio_url) return
  stopPcmAudioStream()
  currentLifecycle?.onCancel?.()
  currentLifecycle = lifecycle ?? null
  cleanup()

  let url = data.audio_url || ''
  if (data.audio_data) {
    const binary = atob(data.audio_data)
    const buffer = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) buffer[i] = binary.charCodeAt(i)
    const blob = new Blob([buffer], { type: `audio/${data.format || 'mp3'}` })
    url = URL.createObjectURL(blob)
    currentBlobUrl = url
  }
  const audio = getAudioElement()
  audio.src = url
  const playbackLifecycle = currentLifecycle

  if (data.volumes?.length) startLipSync(audio, data.volumes, mouthTarget)

  audio.onended = () => {
    const completed = currentLifecycle
    currentLifecycle = null
    stopLipSync()
    if (data.return_to_idle) setExpression('idle')
    cleanup()
    completed?.onComplete?.()
  }

  audio
    .play()
    .then(() => {
      if (currentLifecycle === playbackLifecycle) playbackLifecycle?.onStart?.()
    })
    .catch((error: unknown) => {
      console.warn('[audio] Chat audio playback failed', error)
      const cancelled = currentLifecycle === playbackLifecycle ? playbackLifecycle : null
      if (cancelled) currentLifecycle = null
      cleanup()
      cancelled?.onCancel?.()
    })
}

export function startAudioStream(
  data: AudioStreamStartEvent,
  lifecycle?: AudioPlaybackLifecycle,
  mouthTarget?: MouthTarget,
): void {
  stopLipSync()
  currentLifecycle?.onCancel?.()
  currentLifecycle = null
  cleanup()
  startPcmAudioStream(data, lifecycle, mouthTarget)
}

export function pushAudioStreamChunk(data: AudioStreamChunkEvent): void {
  pushPcmAudioStreamChunk(data)
}

export function endAudioStream(data: AudioStreamEndEvent): void {
  endPcmAudioStream(data)
}

export function stopAudio(): void {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio.currentTime = 0
  }
  const cancelled = currentLifecycle
  currentLifecycle = null
  stopPcmAudioStream()
  stopLipSync()
  cleanup()
  cancelled?.onCancel?.()
}
