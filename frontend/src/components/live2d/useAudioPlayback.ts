import type { ParameterTimeline } from '@/types/socket-events'
import { startLipSync, stopLipSync } from './useLipSync'
import { setExpression } from './useLive2DModel'

// ===== Audio State =====

const SILENT_AUDIO_DATA_URL =
  'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACAgICA'

let currentAudio: HTMLAudioElement | null = null
let currentBlobUrl: string | null = null
let audioUnlocked = false
let unlockPending = false

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
  format?: string
  volumes?: number[]
  expressions?: ParameterTimeline
  return_to_idle?: boolean
}

export function playAudio(data: AudioPlaybackPayload): void {
  if (!data?.audio_data) return
  cleanup()

  const binary = atob(data.audio_data)
  const buffer = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) buffer[i] = binary.charCodeAt(i)

  const blob = new Blob([buffer], { type: `audio/${data.format || 'mp3'}` })
  const url = URL.createObjectURL(blob)
  currentBlobUrl = url
  const audio = getAudioElement()
  audio.src = url

  if (data.volumes?.length) startLipSync(audio, data.volumes)

  audio.onended = () => {
    stopLipSync()
    if (data.return_to_idle) setExpression('idle')
    cleanup()
  }

  audio.play().catch((error: unknown) => {
    console.warn('[audio] Chat audio playback failed', error)
    cleanup()
  })
}

export function stopAudio(): void {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio.currentTime = 0
  }
  stopLipSync()
  cleanup()
}
