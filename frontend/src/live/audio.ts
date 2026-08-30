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
} from '@/shared/audio/playback'
import { startLipSync, stopLipSync } from '@/shared/audio/lipSync'
import {
  clearSingingPlayback,
  readSingingPlayback,
  resolveSingingPlaybackPosition,
  subscribeSingingPlayback,
  writeSingingPlayback,
  type SingingPlaybackSnapshot,
} from '@/singing/playback-sync'
import type { LiveSocket } from './controller'
import type { LiveBgmController } from './bgm'
import type {
  PublicMediaMode,
  PublicMediaOwnerSnapshot,
  PublicMediaOwnership,
  PublicMediaPlaybackPermit,
} from '@/shared/broadcast/mediaOwnership'

export interface LiveAudioController {
  playReviewAudio(request: ReviewAudioPlaybackRequest): void
  dispose(): void
}

export interface ReviewAudioPlaybackRequest {
  taskId: string
  audio: HTMLAudioElement
  volumes: readonly number[]
  runtime?: HTMLElement
}

export interface LiveAudioControllerOptions {
  mediaMode?: PublicMediaMode
  ownership?: PublicMediaOwnership
}

export function createLiveAudioController(
  socket: LiveSocket,
  document: Document,
  setMouthTarget: (value: number, taskId?: string) => void,
  bgm?: Pick<LiveBgmController, 'duck' | 'release' | 'unlock'>,
  options: LiveAudioControllerOptions = {},
): LiveAudioController {
  const status = document.getElementById('audioStatus')
  const singingAudio = document.getElementById('singingAudio') as HTMLAudioElement | null
  const requestedMode = options.ownership?.requestedMode ?? options.mediaMode ?? 'active'
  let singingTaskId = ''
  let singingVolumes: number[] = []
  let currentSingingPlayback: SingingPlaybackSnapshot | null = null
  let singingPlaybackAttempt = 0
  let currentChatTaskId: string | null = null
  let currentReviewTaskId: string | null = null
  let singingPermit: PublicMediaPlaybackPermit | null = null

  const standaloneSnapshot = (): PublicMediaOwnerSnapshot => ({
    requestedMode,
    state: requestedMode,
    ownerId: 'standalone',
    fence: requestedMode === 'active' ? 1 : 0,
  })
  const ownershipSnapshot = (): PublicMediaOwnerSnapshot =>
    options.ownership?.snapshot ?? standaloneSnapshot()
  const syncOwnershipEvidence = (snapshot = ownershipSnapshot()): void => {
    if (!status) return
    status.dataset.audioOwner = snapshot.state
    status.dataset.audioOwnerId = snapshot.ownerId
    status.dataset.audioOwnerFence = String(snapshot.fence)
    status.dataset.audioOwnerRequested = snapshot.requestedMode
  }
  const canPlayMedia = (): boolean => {
    const allowed = options.ownership?.canPlay() ?? requestedMode === 'active'
    syncOwnershipEvidence()
    return allowed
  }
  const ownsMedia = (): boolean => ownershipSnapshot().state === 'active'
  const validatePermit = (permit: PublicMediaPlaybackPermit | null): boolean =>
    !options.ownership || Boolean(permit && options.ownership.validatePlayback(permit))
  const requestPlayback = (
    start: (permit: PublicMediaPlaybackPermit | null) => void,
    unavailable: () => void,
  ): void => {
    if (!options.ownership) {
      if (requestedMode === 'active') start(null)
      else unavailable()
      return
    }
    void options.ownership.acquirePlayback().then((permit) => {
      syncOwnershipEvidence()
      if (!permit || !options.ownership?.validatePlayback(permit)) {
        unavailable()
        return
      }
      start(permit)
    })
  }

  syncOwnershipEvidence()
  if (status && requestedMode !== 'active') {
    status.dataset.playbackState = 'muted'
  }

  const lifecycle = (
    event: Pick<ChatIdentity, 'task_id'>,
    kind: 'chat' | 'singing' | 'review',
    permit: PublicMediaPlaybackPermit | null = null,
  ) => ({
    onStart: () => {
      if (!validatePermit(permit)) {
        stopAudio()
        markUnavailable(event, kind)
        return
      }
      bgm?.duck()
      if (status) {
        status.dataset.playbackCount = String(Number(status.dataset.playbackCount ?? 0) + 1)
        status.dataset.lastAudioTaskId = event.task_id
        status.dataset.lastAudioKind = kind
        status.dataset.playbackState = 'playing'
      }
    },
    onComplete: () => {
      bgm?.release()
      if (kind === 'chat' && currentChatTaskId === event.task_id) currentChatTaskId = null
      if (kind === 'review' && currentReviewTaskId === event.task_id) currentReviewTaskId = null
      if (status) status.dataset.playbackState = 'completed'
    },
    onCancel: () => {
      bgm?.release()
      if (kind === 'chat' && currentChatTaskId === event.task_id) currentChatTaskId = null
      if (kind === 'review' && currentReviewTaskId === event.task_id) currentReviewTaskId = null
      if (status) status.dataset.playbackState = 'cancelled'
    },
  })
  const markPending = (
    event: Pick<ChatIdentity, 'task_id'>,
    kind: 'chat' | 'singing' | 'review' = 'chat',
  ): void => {
    if (!status) return
    status.dataset.lastAudioTaskId = event.task_id
    status.dataset.lastAudioKind = kind
    status.dataset.playbackState = 'pending'
    status.dataset.lipSyncState = 'pending'
    status.dataset.lipSyncAppliedCount = '0'
    status.dataset.lipSyncPeak = '0'
    status.dataset.lastLipSyncTaskId = event.task_id
  }
  const markUnavailable = (
    event: Pick<ChatIdentity, 'task_id'>,
    kind: 'chat' | 'singing' | 'review' = 'chat',
  ): void => {
    if (!status) return
    status.dataset.lastAudioTaskId = event.task_id
    status.dataset.lastAudioKind = kind
    status.dataset.playbackState = requestedMode === 'muted' ? 'muted' : 'standby'
    syncOwnershipEvidence()
  }
  const onAudio = (value: unknown): void => {
    const event = value as AudioWithExpressionEvent
    if (event.turn_id !== event.task_id) return
    requestPlayback(
      (permit) => {
        if (!validatePermit(permit)) return
        currentChatTaskId = event.task_id
        markPending(event)
        playAudio(event, lifecycle(event, 'chat', permit), (value) =>
          setMouthTarget(value, event.task_id),
        )
      },
      () => markUnavailable(event),
    )
  }
  const onStreamStart = (value: unknown): void => {
    const event = value as AudioStreamStartEvent
    if (event.turn_id !== event.task_id) return
    requestPlayback(
      (permit) => {
        if (!validatePermit(permit)) return
        currentChatTaskId = event.task_id
        markPending(event)
        startAudioStream(event, lifecycle(event, 'chat', permit), (value) =>
          setMouthTarget(value, event.task_id),
        )
      },
      () => markUnavailable(event),
    )
  }
  const onStreamChunk = (value: unknown): void => {
    if (currentChatTaskId && canPlayMedia()) pushAudioStreamChunk(value as AudioStreamChunkEvent)
  }
  const onStreamEnd = (value: unknown): void => {
    if (currentChatTaskId && canPlayMedia()) endAudioStream(value as AudioStreamEndEvent)
  }
  const onStop = (value: unknown): void => {
    if (!ownsMedia()) return
    const event = value as ChatIdentity
    if (
      event.turn_id !== event.task_id ||
      (event.task_id !== currentChatTaskId && event.task_id !== currentReviewTaskId)
    ) {
      return
    }
    stopAudio()
    currentChatTaskId = null
    currentReviewTaskId = null
    if (singingAudio && !singingAudio.paused) singingAudio.pause()
    bgm?.release()
  }
  const onSingingPlay = (): void => {
    if (!ownsMedia() || !singingAudio || !singingTaskId) return
    lifecycle({ task_id: singingTaskId }, 'singing', singingPermit).onStart()
    if (singingVolumes.length) {
      startLipSync(singingAudio, singingVolumes, (value) => setMouthTarget(value, singingTaskId))
    }
  }
  const onSingingPause = (): void => {
    if (!ownsMedia() || !singingAudio || singingAudio.ended || !singingTaskId) return
    stopLipSync()
    bgm?.release()
    if (status?.dataset.playbackState === 'playing') status.dataset.playbackState = 'paused'
  }
  const onSingingEnded = (): void => {
    if (!ownsMedia() || !singingTaskId) return
    stopLipSync()
    lifecycle({ task_id: singingTaskId }, 'singing', singingPermit).onComplete()
  }
  const onSingingError = (): void => {
    if (!ownsMedia()) return
    stopLipSync()
    bgm?.release()
    if (currentSingingPlayback) clearSingingPlayback(currentSingingPlayback.taskId)
    currentSingingPlayback = null
    if (status) status.dataset.playbackState = 'error'
  }
  const beginSingingPlayback = (
    snapshot: SingingPlaybackSnapshot,
    permit: PublicMediaPlaybackPermit | null,
  ): void => {
    if (!validatePermit(permit)) return
    if (!singingAudio) return
    singingPermit = permit
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
      void singingAudio
        .play()
        .then(() => {
          if (playbackAttempt !== singingPlaybackAttempt || validatePermit(permit)) return
          singingAudio.pause()
          markUnavailable({ task_id: snapshot.taskId }, 'singing')
        })
        .catch((error: unknown) => {
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
  const applySingingPlayback = (snapshot: SingingPlaybackSnapshot): void => {
    requestPlayback(
      (permit) => beginSingingPlayback(snapshot, permit),
      () => markUnavailable({ task_id: snapshot.taskId }, 'singing'),
    )
  }
  const onPlaybackGesture = (): void => {
    if (!canPlayMedia()) return
    unlockAudioPlayback()
    bgm?.unlock()
    if (currentSingingPlayback?.state === 'playing' && singingAudio?.paused) {
      applySingingPlayback(currentSingingPlayback)
    }
  }
  const onSingingComplete = (value: unknown): void => {
    if (!value || typeof value !== 'object') return
    const event = value as Record<string, unknown>
    if (typeof event.task_id !== 'string' || typeof event.audio_url !== 'string') return
    requestPlayback(
      (permit) => {
        const snapshot = writeSingingPlayback({
          taskId: event.task_id as string,
          track: 'mix',
          audioUrl: event.audio_url as string,
          volumes: Array.isArray(event.volumes) ? (event.volumes as number[]) : [],
          durationSeconds: typeof event.duration === 'number' ? event.duration : 0,
          state: 'playing',
          positionSeconds: 0,
          updatedAtMs: Date.now(),
        })
        beginSingingPlayback(snapshot, permit)
      },
      () => markUnavailable({ task_id: event.task_id as string }, 'singing'),
    )
  }

  const playReviewAudio = (request: ReviewAudioPlaybackRequest): void => {
    const event = { task_id: request.taskId }
    requestPlayback(
      (permit) => {
        if (!validatePermit(permit)) return
        currentReviewTaskId = request.taskId
        request.audio.dataset.complete = 'pending'
        markPending(event, 'review')
        const sharedLifecycle = lifecycle(event, 'review', permit)
        playAudio(
          { audio_url: request.audio.src, volumes: [...request.volumes] },
          {
            onStart: () => {
              sharedLifecycle.onStart()
              if (validatePermit(permit)) request.audio.dataset.complete = 'playing'
            },
            onComplete: () => {
              sharedLifecycle.onComplete()
              request.audio.dataset.complete = 'true'
            },
            onCancel: () => {
              sharedLifecycle.onCancel()
              request.audio.dataset.complete = 'cancelled'
            },
          },
          (value) => {
            if (value > 0) request.runtime?.setAttribute('data-lip-sync', 'observed')
            setMouthTarget(value, request.taskId)
          },
        )
      },
      () => {
        request.audio.dataset.complete = requestedMode === 'muted' ? 'muted' : 'standby'
        markUnavailable(event, 'review')
      },
    )
  }

  singingAudio?.addEventListener('play', onSingingPlay)
  singingAudio?.addEventListener('pause', onSingingPause)
  singingAudio?.addEventListener('ended', onSingingEnded)
  singingAudio?.addEventListener('error', onSingingError)
  if (requestedMode === 'active') {
    document.addEventListener('pointerdown', onPlaybackGesture, { capture: true })
    document.addEventListener('keydown', onPlaybackGesture, { capture: true })
  }
  socket.on(Events.CHAT.AUDIO_WITH_EXPRESSION, onAudio)
  socket.on(Events.CHAT.AUDIO_STREAM_START, onStreamStart)
  socket.on(Events.CHAT.AUDIO_STREAM_CHUNK, onStreamChunk)
  socket.on(Events.CHAT.AUDIO_STREAM_END, onStreamEnd)
  socket.on(Events.CHAT.STOP_AUDIO, onStop)
  socket.on(Events.SING.COMPLETE, onSingingComplete)
  const unsubscribeSingingPlayback =
    requestedMode === 'active' ? subscribeSingingPlayback(applySingingPlayback) : () => undefined
  const persistedSingingPlayback = requestedMode === 'active' ? readSingingPlayback() : null
  if (persistedSingingPlayback) applySingingPlayback(persistedSingingPlayback)
  let observedOwnerState = ownershipSnapshot().state
  const unsubscribeOwnership = options.ownership?.subscribe((snapshot) => {
    const previous = observedOwnerState
    observedOwnerState = snapshot.state
    syncOwnershipEvidence(snapshot)
    if (snapshot.state !== 'active') {
      if (currentChatTaskId || currentReviewTaskId) {
        stopAudio()
        currentChatTaskId = null
        currentReviewTaskId = null
      }
      if (singingAudio && !singingAudio.paused) singingAudio.pause()
      if (status) status.dataset.playbackState = snapshot.state
      return
    }
    if (previous !== 'active') {
      const persisted = readSingingPlayback()
      if (persisted) applySingingPlayback(persisted)
    }
  })

  return {
    playReviewAudio,
    dispose(): void {
      if (requestedMode === 'active') {
        document.removeEventListener('pointerdown', onPlaybackGesture, { capture: true })
        document.removeEventListener('keydown', onPlaybackGesture, { capture: true })
      }
      socket.off(Events.CHAT.AUDIO_WITH_EXPRESSION, onAudio)
      socket.off(Events.CHAT.AUDIO_STREAM_START, onStreamStart)
      socket.off(Events.CHAT.AUDIO_STREAM_CHUNK, onStreamChunk)
      socket.off(Events.CHAT.AUDIO_STREAM_END, onStreamEnd)
      socket.off(Events.CHAT.STOP_AUDIO, onStop)
      socket.off(Events.SING.COMPLETE, onSingingComplete)
      unsubscribeSingingPlayback()
      unsubscribeOwnership?.()
      singingAudio?.removeEventListener('play', onSingingPlay)
      singingAudio?.removeEventListener('pause', onSingingPause)
      singingAudio?.removeEventListener('ended', onSingingEnded)
      singingAudio?.removeEventListener('error', onSingingError)
      if (singingAudio) {
        singingAudio.pause()
        singingAudio.removeAttribute('src')
        singingAudio.load()
      }
      if (ownsMedia()) stopAudio()
    },
  }
}
