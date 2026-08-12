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
import { startLipSync, stopLipSync, type MouthTarget } from '@/components/live2d/useLipSync'
import {
  clearSingingPlayback,
  readSingingPlayback,
  resolveSingingPlaybackPosition,
  subscribeSingingPlayback,
  writeSingingPlayback,
  type SingingPlaybackSnapshot,
} from '@/singing/playback-sync'
import type { LiveSocket } from './controller'

export interface LiveAudioController {
  dispose(): void
}

export function createLiveAudioController(
  socket: LiveSocket,
  document: Document,
  setMouthTarget: MouthTarget,
): LiveAudioController {
  const status = document.getElementById('audioStatus')
  const singingAudio = document.getElementById('singingAudio') as HTMLAudioElement | null
  let singingTaskId = ''
  let singingVolumes: number[] = []
  let currentSingingPlayback: SingingPlaybackSnapshot | null = null
  let singingPlaybackAttempt = 0

  const lifecycle = (event: Pick<ChatIdentity, 'task_id'>, kind: 'chat' | 'singing') => ({
    onStart: () => {
      if (status) {
        status.dataset.playbackCount = String(Number(status.dataset.playbackCount ?? 0) + 1)
        status.dataset.lastAudioTaskId = event.task_id
        status.dataset.lastAudioKind = kind
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
  const markPending = (
    event: Pick<ChatIdentity, 'task_id'>,
    kind: 'chat' | 'singing' = 'chat',
  ): void => {
    if (!status) return
    status.dataset.lastAudioTaskId = event.task_id
    status.dataset.lastAudioKind = kind
    status.dataset.playbackState = 'pending'
  }
  const onAudio = (value: unknown): void => {
    const event = value as AudioWithExpressionEvent
    markPending(event)
    playAudio(event, lifecycle(event, 'chat'), setMouthTarget)
  }
  const onStreamStart = (value: unknown): void => {
    const event = value as AudioStreamStartEvent
    markPending(event)
    startAudioStream(event, lifecycle(event, 'chat'), setMouthTarget)
  }
  const onStreamChunk = (value: unknown): void =>
    pushAudioStreamChunk(value as AudioStreamChunkEvent)
  const onStreamEnd = (value: unknown): void => endAudioStream(value as AudioStreamEndEvent)
  const onStop = (): void => {
    stopAudio()
    if (singingAudio && !singingAudio.paused) singingAudio.pause()
  }
  const onSingingPlay = (): void => {
    if (!singingAudio || !singingTaskId) return
    lifecycle({ task_id: singingTaskId }, 'singing').onStart()
    if (singingVolumes.length) startLipSync(singingAudio, singingVolumes, setMouthTarget)
  }
  const onSingingPause = (): void => {
    if (!singingAudio || singingAudio.ended || !singingTaskId) return
    stopLipSync()
    if (status?.dataset.playbackState === 'playing') status.dataset.playbackState = 'paused'
  }
  const onSingingEnded = (): void => {
    if (!singingTaskId) return
    stopLipSync()
    lifecycle({ task_id: singingTaskId }, 'singing').onComplete()
  }
  const onSingingError = (): void => {
    stopLipSync()
    if (currentSingingPlayback) clearSingingPlayback(currentSingingPlayback.taskId)
    currentSingingPlayback = null
    if (status) status.dataset.playbackState = 'error'
  }
  const applySingingPlayback = (snapshot: SingingPlaybackSnapshot): void => {
    if (!singingAudio) return
    currentSingingPlayback = snapshot
    const playbackAttempt = ++singingPlaybackAttempt
    stopAudio()
    singingTaskId = snapshot.taskId
    singingVolumes = snapshot.volumes
    markPending({ task_id: snapshot.taskId }, 'singing')
    const srcChanged = singingAudio.getAttribute('src') !== snapshot.audioUrl
    if (srcChanged) {
      singingAudio.pause()
      singingAudio.src = snapshot.audioUrl
      singingAudio.load()
    }
    const position = resolveSingingPlaybackPosition(snapshot)
    // Some browsers throw InvalidStateError before metadata has loaded.
    const seekToPosition = () => {
      try {
        singingAudio.currentTime = position
      } catch {
        /* ignore */
      }
    }
    seekToPosition()
    if (srcChanged) {
      // Browsers defer currentTime while readyState is HAVE_NOTHING; re-apply
      // once metadata arrives so cross-tab playback resumes at the right spot.
      singingAudio.addEventListener(
        'loadedmetadata',
        () => {
          if (playbackAttempt !== singingPlaybackAttempt) return
          if (singingAudio.getAttribute('src') !== snapshot.audioUrl) return
          seekToPosition()
        },
        { once: true },
      )
    }
    if (
      snapshot.state === 'playing' &&
      (snapshot.durationSeconds === 0 || position < snapshot.durationSeconds)
    ) {
      void singingAudio.play().catch((error: unknown) => {
        if (playbackAttempt !== singingPlaybackAttempt) return
        console.warn('[audio] Singing audio playback failed', error)
        const name = error instanceof DOMException ? error.name : ''
        const message = error instanceof Error ? error.message : String(error)
        if (name === 'NotAllowedError' || message.includes('NotAllowedError')) {
          if (status) status.dataset.playbackState = 'blocked'
          return
        }
        onSingingError()
      })
      return
    }
    singingAudio.pause()
    stopLipSync()
    if (status) {
      status.dataset.playbackState = snapshot.state === 'playing' ? 'completed' : snapshot.state
    }
  }
  const onPlaybackGesture = (): void => {
    unlockAudioPlayback()
    if (currentSingingPlayback?.state === 'playing' && singingAudio?.paused) {
      applySingingPlayback(currentSingingPlayback)
    }
  }
  const onSingingComplete = (value: unknown): void => {
    if (!value || typeof value !== 'object') return
    const event = value as Record<string, unknown>
    if (typeof event.task_id !== 'string' || typeof event.audio_url !== 'string') return
    const snapshot = writeSingingPlayback({
      taskId: event.task_id,
      track: 'mix',
      audioUrl: event.audio_url,
      volumes: Array.isArray(event.volumes) ? (event.volumes as number[]) : [],
      durationSeconds: typeof event.duration === 'number' ? event.duration : 0,
      state: 'playing',
      positionSeconds: 0,
      updatedAtMs: Date.now(),
    })
    applySingingPlayback(snapshot)
  }

  singingAudio?.addEventListener('play', onSingingPlay)
  singingAudio?.addEventListener('pause', onSingingPause)
  singingAudio?.addEventListener('ended', onSingingEnded)
  singingAudio?.addEventListener('error', onSingingError)
  document.addEventListener('pointerdown', onPlaybackGesture, { capture: true })
  document.addEventListener('keydown', onPlaybackGesture, { capture: true })
  socket.on(Events.CHAT.AUDIO_WITH_EXPRESSION, onAudio)
  socket.on(Events.CHAT.AUDIO_STREAM_START, onStreamStart)
  socket.on(Events.CHAT.AUDIO_STREAM_CHUNK, onStreamChunk)
  socket.on(Events.CHAT.AUDIO_STREAM_END, onStreamEnd)
  socket.on(Events.CHAT.STOP_AUDIO, onStop)
  socket.on(Events.SING.COMPLETE, onSingingComplete)
  const unsubscribeSingingPlayback = subscribeSingingPlayback(applySingingPlayback)
  const persistedSingingPlayback = readSingingPlayback()
  if (persistedSingingPlayback) applySingingPlayback(persistedSingingPlayback)

  return {
    dispose(): void {
      document.removeEventListener('pointerdown', onPlaybackGesture, { capture: true })
      document.removeEventListener('keydown', onPlaybackGesture, { capture: true })
      socket.off(Events.CHAT.AUDIO_WITH_EXPRESSION, onAudio)
      socket.off(Events.CHAT.AUDIO_STREAM_START, onStreamStart)
      socket.off(Events.CHAT.AUDIO_STREAM_CHUNK, onStreamChunk)
      socket.off(Events.CHAT.AUDIO_STREAM_END, onStreamEnd)
      socket.off(Events.CHAT.STOP_AUDIO, onStop)
      socket.off(Events.SING.COMPLETE, onSingingComplete)
      unsubscribeSingingPlayback()
      singingAudio?.removeEventListener('play', onSingingPlay)
      singingAudio?.removeEventListener('pause', onSingingPause)
      singingAudio?.removeEventListener('ended', onSingingEnded)
      singingAudio?.removeEventListener('error', onSingingError)
      if (singingAudio) {
        singingAudio.pause()
        singingAudio.removeAttribute('src')
        singingAudio.load()
      }
      stopAudio()
    },
  }
}
