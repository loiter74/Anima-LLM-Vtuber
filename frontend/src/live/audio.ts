import { Events } from '@/constants/socket-events'
import type {
  AudioStreamChunkEvent,
  AudioStreamEndEvent,
  AudioStreamStartEvent,
  AudioWithExpressionEvent,
  ChatIdentity,
} from '@/types/socket-events'
import {
  endAudioStream,
  playAudio,
  pushAudioStreamChunk,
  startAudioStream,
  stopAudio,
  unlockAudioPlayback,
} from '@/components/live2d/useAudioPlayback'
import type { LiveSocket } from './controller'

export interface LiveAudioController {
  dispose(): void
}

export function createLiveAudioController(
  socket: LiveSocket,
  document: Document,
): LiveAudioController {
  const status = document.getElementById('audioStatus')
  const lifecycle = (event: ChatIdentity) => ({
    onStart: () => {
      if (status) {
        status.dataset.playbackCount = String(Number(status.dataset.playbackCount ?? 0) + 1)
        status.dataset.lastAudioTaskId = event.task_id
        status.dataset.playbackState = 'playing'
      }
    },
    onComplete: () => {
      if (status) status.dataset.playbackState = 'completed'
    },
    onCancel: () => {
      if (status) status.dataset.playbackState = 'cancelled'
    },
  })
  const markPending = (event: ChatIdentity): void => {
    if (!status) return
    status.dataset.lastAudioTaskId = event.task_id
    status.dataset.playbackState = 'pending'
  }
  const onAudio = (value: unknown): void => {
    const event = value as AudioWithExpressionEvent
    markPending(event)
    playAudio(event, lifecycle(event))
  }
  const onStreamStart = (value: unknown): void => {
    const event = value as AudioStreamStartEvent
    markPending(event)
    startAudioStream(event, lifecycle(event))
  }
  const onStreamChunk = (value: unknown): void =>
    pushAudioStreamChunk(value as AudioStreamChunkEvent)
  const onStreamEnd = (value: unknown): void => endAudioStream(value as AudioStreamEndEvent)
  const onStop = (): void => stopAudio()

  document.addEventListener('pointerdown', unlockAudioPlayback, { capture: true })
  document.addEventListener('keydown', unlockAudioPlayback, { capture: true })
  socket.on(Events.CHAT.AUDIO_WITH_EXPRESSION, onAudio)
  socket.on(Events.CHAT.AUDIO_STREAM_START, onStreamStart)
  socket.on(Events.CHAT.AUDIO_STREAM_CHUNK, onStreamChunk)
  socket.on(Events.CHAT.AUDIO_STREAM_END, onStreamEnd)
  socket.on(Events.CHAT.STOP_AUDIO, onStop)

  return {
    dispose(): void {
      document.removeEventListener('pointerdown', unlockAudioPlayback, { capture: true })
      document.removeEventListener('keydown', unlockAudioPlayback, { capture: true })
      socket.off(Events.CHAT.AUDIO_WITH_EXPRESSION, onAudio)
      socket.off(Events.CHAT.AUDIO_STREAM_START, onStreamStart)
      socket.off(Events.CHAT.AUDIO_STREAM_CHUNK, onStreamChunk)
      socket.off(Events.CHAT.AUDIO_STREAM_END, onStreamEnd)
      socket.off(Events.CHAT.STOP_AUDIO, onStop)
      stopAudio()
    },
  }
}
