import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Events } from '@/constants/socket-events'
import { createLiveAudioController } from './audio'
import type { LiveSocket } from './controller'
import { SINGING_PLAYBACK_STORAGE_KEY, writeSingingPlayback } from '@/singing/playback-sync'
import {
  createPublicMediaOwnership,
  type PublicMediaLock,
  type PublicMediaLockManager,
} from '@/shared/broadcast/mediaOwnership'

const playback = vi.hoisted(() => ({
  endAudioStream: vi.fn(),
  playAudio: vi.fn(),
  pushAudioStreamChunk: vi.fn(),
  startAudioStream: vi.fn(),
  stopAudio: vi.fn(),
  unlockAudioPlayback: vi.fn(),
}))
const lipSync = vi.hoisted(() => ({
  startLipSync: vi.fn(),
  stopLipSync: vi.fn(),
}))

vi.mock('@/shared/audio/playback', () => playback)
vi.mock('@/shared/audio/lipSync', () => lipSync)

class FakeLockManager implements PublicMediaLockManager {
  private readonly held = new Set<string>()

  async request(
    name: string,
    _options: { mode: 'exclusive'; ifAvailable: true },
    callback: (lock: PublicMediaLock | null) => Promise<void> | void,
  ): Promise<void> {
    if (this.held.has(name)) {
      await callback(null)
      return
    }
    this.held.add(name)
    try {
      await callback({ name })
    } finally {
      this.held.delete(name)
    }
  }
}

function harness(
  playResult: Promise<void> = Promise.resolve(),
  mediaMode: 'active' | 'muted' = 'active',
) {
  const handlers = new Map<string, (...args: unknown[]) => void>()
  const setMouthTarget = vi.fn()
  const socket: LiveSocket = {
    on: vi.fn((event, handler) => {
      handlers.set(event, handler)
      return socket
    }),
    off: vi.fn((event, handler) => {
      if (handlers.get(event) === handler) handlers.delete(event)
      return socket
    }),
  }
  document.body.innerHTML = `
    <span id="audioStatus" data-playback-state="idle" data-playback-count="0" hidden></span>
    <span id="livestreamStatus" data-last-bilibili-reply-id="reply-task"></span>
    <audio id="singingAudio" hidden></audio>
  `
  const singingAudio = document.getElementById('singingAudio') as HTMLAudioElement
  vi.spyOn(singingAudio, 'play').mockReturnValue(playResult)
  vi.spyOn(singingAudio, 'pause').mockImplementation(() => undefined)
  vi.spyOn(singingAudio, 'load').mockImplementation(() => undefined)
  const bgm = { duck: vi.fn(), release: vi.fn(), unlock: vi.fn() }
  const controller = createLiveAudioController(socket, document, setMouthTarget, bgm, { mediaMode })
  return { bgm, controller, handlers, setMouthTarget, singingAudio, socket }
}

describe('standalone live audio', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('restores dashboard singing playback when live opens later', () => {
    writeSingingPlayback({
      taskId: 'late-live-task',
      track: 'mix',
      audioUrl: '/api/singing/audio/late_final.wav',
      volumes: [0.2, 0.7],
      durationSeconds: 240,
      state: 'playing',
      positionSeconds: 18,
      updatedAtMs: Date.now(),
    })

    const { controller, setMouthTarget, singingAudio } = harness()

    expect(singingAudio.getAttribute('src')).toBe('/api/singing/audio/late_final.wav')
    expect(singingAudio.currentTime).toBeCloseTo(18, 0)
    expect(singingAudio.play).toHaveBeenCalledOnce()
    singingAudio.dispatchEvent(new Event('play'))
    expect(lipSync.startLipSync).toHaveBeenCalledWith(
      singingAudio,
      [0.2, 0.7],
      expect.any(Function),
    )
    const mouthTarget = lipSync.startLipSync.mock.calls[0][2]
    mouthTarget(0.6)
    expect(setMouthTarget).toHaveBeenCalledWith(0.6, 'late-live-task')
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.lastAudioTaskId',
      'late-live-task',
    )
    controller.dispose()
  })

  it('applies dashboard pause and seek changes without a new socket event', () => {
    const { controller, singingAudio } = harness()
    const playing = {
      version: 1 as const,
      taskId: 'controlled-task',
      track: 'mix' as const,
      audioUrl: '/api/singing/audio/controlled.wav',
      volumes: [0.4],
      durationSeconds: 200,
      state: 'playing' as const,
      positionSeconds: 20,
      updatedAtMs: Date.now(),
    }
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SINGING_PLAYBACK_STORAGE_KEY,
        newValue: JSON.stringify(playing),
      }),
    )
    expect(singingAudio.play).toHaveBeenCalledOnce()

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SINGING_PLAYBACK_STORAGE_KEY,
        newValue: JSON.stringify({
          ...playing,
          state: 'paused',
          positionSeconds: 31,
          updatedAtMs: Date.now(),
        }),
      }),
    )

    expect(singingAudio.currentTime).toBe(31)
    expect(singingAudio.pause).toHaveBeenCalled()
    expect(document.getElementById('audioStatus')).toHaveProperty('dataset.playbackState', 'paused')
    controller.dispose()
  })

  it('retries browser-blocked singing playback on the first live page gesture', async () => {
    writeSingingPlayback({
      taskId: 'gesture-task',
      track: 'mix',
      audioUrl: '/gesture.wav',
      volumes: [0.3],
      durationSeconds: 120,
      state: 'playing',
      positionSeconds: 4,
      updatedAtMs: Date.now(),
    })
    const { controller, singingAudio } = harness(Promise.reject(new Error('NotAllowedError')))
    await Promise.resolve()
    await Promise.resolve()
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.playbackState',
      'blocked',
    )

    vi.mocked(singingAudio.play).mockResolvedValue()
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))

    expect(singingAudio.play).toHaveBeenCalledTimes(2)
    expect(playback.unlockAudioPlayback).toHaveBeenCalledOnce()
    controller.dispose()
  })

  it('does not miss a gesture that arrives before autoplay rejection settles', async () => {
    writeSingingPlayback({
      taskId: 'early-gesture-task',
      track: 'mix',
      audioUrl: '/early-gesture.wav',
      volumes: [0.4],
      durationSeconds: 120,
      state: 'playing',
      positionSeconds: 2,
      updatedAtMs: Date.now(),
    })
    const { controller, singingAudio } = harness(Promise.reject(new Error('NotAllowedError')))
    vi.mocked(singingAudio.play).mockResolvedValue()

    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await Promise.resolve()
    await Promise.resolve()

    expect(singingAudio.play).toHaveBeenCalledTimes(2)
    expect(document.getElementById('audioStatus')?.dataset.playbackState).not.toBe('error')
    controller.dispose()
  })

  it('forgets an unavailable persisted singing track instead of retrying it on every load', () => {
    writeSingingPlayback({
      taskId: 'missing-task',
      track: 'mix',
      audioUrl: '/missing.wav',
      volumes: [],
      durationSeconds: 120,
      state: 'playing',
      positionSeconds: 0,
      updatedAtMs: Date.now(),
    })
    const { controller, singingAudio } = harness()

    singingAudio.dispatchEvent(new Event('error'))

    expect(localStorage.getItem(SINGING_PLAYBACK_STORAGE_KEY)).toBeNull()
    expect(document.getElementById('audioStatus')).toHaveProperty('dataset.playbackState', 'error')
    controller.dispose()
  })

  it('routes complete and progressive TTS events through the shared player', () => {
    const { bgm, controller, handlers } = harness()
    const identity = {
      message_id: 'message',
      conversation_id: 'conversation',
      task_id: 'task',
      turn_id: 'task',
    }
    const complete = { ...identity, audio_data: 'audio', format: 'wav' }
    const start = {
      ...identity,
      stream_id: 'stream',
      format: 'pcm_s16le',
      sample_rate: 24_000,
      channels: 1,
    }
    const chunk = { stream_id: 'stream', sequence: 0, audio_data: 'chunk' }
    const end = { stream_id: 'stream', final_sequence: 0, status: 'completed' }

    handlers.get(Events.CHAT.AUDIO_WITH_EXPRESSION)!(complete)
    handlers.get(Events.CHAT.AUDIO_STREAM_START)!(start)
    handlers.get(Events.CHAT.AUDIO_STREAM_CHUNK)!(chunk)
    handlers.get(Events.CHAT.AUDIO_STREAM_END)!(end)
    handlers.get(Events.CHAT.STOP_AUDIO)!({ ...identity, task_id: 'stale', turn_id: 'stale' })
    expect(playback.stopAudio).not.toHaveBeenCalled()
    handlers.get(Events.CHAT.STOP_AUDIO)!(identity)

    expect(playback.playAudio).toHaveBeenCalledWith(
      complete,
      expect.any(Object),
      expect.any(Function),
    )
    expect(playback.startAudioStream).toHaveBeenCalledWith(
      start,
      expect.any(Object),
      expect.any(Function),
    )
    expect(playback.pushAudioStreamChunk).toHaveBeenCalledWith(chunk)
    expect(playback.endAudioStream).toHaveBeenCalledWith(end)
    expect(playback.stopAudio).toHaveBeenCalledOnce()
    expect(bgm.release).toHaveBeenCalledOnce()
    bgm.release.mockClear()

    const lifecycle = playback.playAudio.mock.calls[0][1]
    lifecycle.onStart()
    expect(bgm.duck).toHaveBeenCalledOnce()
    expect(document.getElementById('audioStatus')).toHaveProperty('dataset.playbackCount', '1')
    expect(document.getElementById('audioStatus')).toHaveProperty('dataset.lastAudioTaskId', 'task')
    lifecycle.onComplete()
    expect(bgm.release).toHaveBeenCalledOnce()
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.playbackState',
      'completed',
    )
    controller.dispose()
  })

  it('records correlated audio while the muted surface never starts playback', () => {
    const { controller, handlers } = harness(Promise.resolve(), 'muted')
    const identity = {
      message_id: 'message',
      conversation_id: 'conversation',
      task_id: 'muted-task',
      turn_id: 'muted-task',
    }

    handlers.get(Events.CHAT.AUDIO_WITH_EXPRESSION)!({
      ...identity,
      audio_data: 'audio',
      format: 'wav',
    })
    handlers.get(Events.CHAT.AUDIO_STREAM_START)!({
      ...identity,
      stream_id: 'stream',
      format: 'pcm_s16le',
      sample_rate: 24_000,
      channels: 1,
    })
    handlers.get(Events.SING.COMPLETE)!({ task_id: 'muted-song', audio_url: '/song.wav' })
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))

    const status = document.getElementById('audioStatus')!
    expect(status.dataset.audioOwner).toBe('muted')
    expect(status.dataset.playbackState).toBe('muted')
    expect(status.dataset.playbackCount).toBe('0')
    expect(status.dataset.lastAudioTaskId).toBe('muted-song')
    expect(playback.playAudio).not.toHaveBeenCalled()
    expect(playback.startAudioStream).not.toHaveBeenCalled()
    expect(playback.unlockAudioPlayback).not.toHaveBeenCalled()
    controller.dispose()
    expect(playback.stopAudio).not.toHaveBeenCalled()
  })

  it('plays a shared task only after a concurrent active candidate wins fencing', async () => {
    const handlers = new Map<string, Array<(...args: unknown[]) => void>>()
    const socket: LiveSocket = {
      on: vi.fn((event, handler) => {
        handlers.set(event, [...(handlers.get(event) ?? []), handler])
        return socket
      }),
      off: vi.fn((event, handler) => {
        handlers.set(
          event,
          (handlers.get(event) ?? []).filter((registered) => registered !== handler),
        )
        return socket
      }),
    }
    const page = (): Document => {
      const pageDocument = document.implementation.createHTMLDocument()
      pageDocument.body.innerHTML = `
        <span id="audioStatus" data-playback-state="idle" data-playback-count="0"></span>
        <audio id="singingAudio"></audio>
      `
      const audio = pageDocument.getElementById('singingAudio') as HTMLAudioElement
      vi.spyOn(audio, 'pause').mockImplementation(() => undefined)
      vi.spyOn(audio, 'load').mockImplementation(() => undefined)
      return pageDocument
    }
    const liveDocument = page()
    const gameplayDocument = page()
    const lockManager = new FakeLockManager()
    const liveOwnership = createPublicMediaOwnership(
      new URLSearchParams('media=active'),
      'active',
      { ownerId: 'live-page', lockManager, retryMs: 5 },
    )
    const gameplayOwnership = createPublicMediaOwnership(
      new URLSearchParams('media=active'),
      'muted',
      { ownerId: 'gameplay-page', lockManager, retryMs: 5 },
    )
    const liveController = createLiveAudioController(socket, liveDocument, vi.fn(), undefined, {
      ownership: liveOwnership,
    })
    const gameplayController = createLiveAudioController(
      socket,
      gameplayDocument,
      vi.fn(),
      undefined,
      { ownership: gameplayOwnership },
    )
    let resolvedLifecycle: { onStart?: () => void } | undefined
    playback.playAudio.mockImplementationOnce(
      (_event: unknown, lifecycle: { onStart?: () => void }) => {
        resolvedLifecycle = lifecycle
      },
    )

    for (const handler of handlers.get(Events.CHAT.AUDIO_WITH_EXPRESSION) ?? []) {
      handler({
        message_id: 'shared-task',
        conversation_id: 'shared-task',
        task_id: 'shared-task',
        turn_id: 'shared-task',
        audio_data: 'audio',
        format: 'wav',
      })
    }

    await vi.waitFor(() => expect(playback.playAudio).toHaveBeenCalledOnce())
    expect(liveDocument.getElementById('audioStatus')?.dataset.audioOwner).toBe('active')
    expect(gameplayDocument.getElementById('audioStatus')?.dataset.audioOwner).toBe('standby')

    liveOwnership.dispose()
    await vi.waitFor(() =>
      expect(gameplayDocument.getElementById('audioStatus')?.dataset.audioOwner).toBe('active'),
    )
    playback.stopAudio.mockClear()
    resolvedLifecycle?.onStart?.()
    expect(playback.stopAudio).toHaveBeenCalledOnce()
    expect(liveDocument.getElementById('audioStatus')?.dataset.playbackCount).toBe('0')
    expect(liveDocument.getElementById('audioStatus')?.dataset.playbackState).toBe('standby')

    playback.playAudio.mockClear()
    for (const handler of handlers.get(Events.CHAT.AUDIO_WITH_EXPRESSION) ?? []) {
      handler({
        message_id: 'replacement-task',
        conversation_id: 'replacement-task',
        task_id: 'replacement-task',
        turn_id: 'replacement-task',
        audio_data: 'audio',
        format: 'wav',
      })
    }
    await vi.waitFor(() => expect(playback.playAudio).toHaveBeenCalledOnce())
    playback.playAudio.mock.calls[0][1].onStart()
    expect(gameplayDocument.getElementById('audioStatus')?.dataset.playbackCount).toBe('1')
    expect(gameplayDocument.getElementById('audioStatus')?.dataset.lastAudioTaskId).toBe(
      'replacement-task',
    )
    liveController.dispose()
    gameplayController.dispose()
    gameplayOwnership.dispose()
  })

  it('plays review TTS through the shared lifecycle and persists actual playback evidence', () => {
    const { controller, setMouthTarget } = harness()
    const runtime = document.createElement('section')
    const audio = document.createElement('audio')
    audio.src = 'http://127.0.0.1:49152/review.wav'
    audio.dataset.complete = 'pending'
    runtime.dataset.lipSync = 'pending'

    controller.playReviewAudio({ taskId: 'review-task', audio, volumes: [0.2, 0.8], runtime })

    expect(playback.playAudio).toHaveBeenCalledWith(
      { audio_url: audio.src, volumes: [0.2, 0.8] },
      expect.any(Object),
      expect.any(Function),
    )
    const [, lifecycle, mouthTarget] = playback.playAudio.mock.calls.at(-1)!
    lifecycle.onStart()
    mouthTarget(0.8)
    expect(setMouthTarget).toHaveBeenCalledWith(0.8, 'review-task')
    expect(runtime.dataset.lipSync).toBe('observed')
    expect(document.getElementById('audioStatus')?.dataset).toEqual(
      expect.objectContaining({
        audioOwner: 'active',
        playbackCount: '1',
        lastAudioTaskId: 'review-task',
        lastAudioKind: 'review',
        playbackState: 'playing',
      }),
    )

    lifecycle.onComplete()
    expect(audio.dataset.complete).toBe('true')
    expect(document.getElementById('audioStatus')?.dataset.playbackState).toBe('completed')
    controller.dispose()
  })

  it('keeps review TTS silent when muted and cancels it on generation stop', () => {
    const muted = harness(Promise.resolve(), 'muted')
    const mutedAudio = document.createElement('audio')
    mutedAudio.src = 'http://127.0.0.1:49152/muted.wav'
    muted.controller.playReviewAudio({ taskId: 'muted-review', audio: mutedAudio, volumes: [] })
    expect(playback.playAudio).not.toHaveBeenCalled()
    expect(mutedAudio.dataset.complete).toBe('muted')
    muted.controller.dispose()

    const active = harness()
    const activeAudio = document.createElement('audio')
    activeAudio.src = 'http://127.0.0.1:49152/active.wav'
    active.controller.playReviewAudio({ taskId: 'active-review', audio: activeAudio, volumes: [] })
    const lifecycle = playback.playAudio.mock.calls.at(-1)?.[1]
    lifecycle.onStart()
    playback.stopAudio.mockImplementationOnce(() => lifecycle.onCancel())
    active.handlers.get(Events.CHAT.STOP_AUDIO)!({
      message_id: 'active-review',
      conversation_id: 'active-review',
      task_id: 'active-review',
      turn_id: 'active-review',
    })
    expect(activeAudio.dataset.complete).toBe('cancelled')
    expect(document.getElementById('audioStatus')?.dataset.playbackState).toBe('cancelled')
    active.controller.dispose()
  })

  it('exposes the same task identity for a Bilibili reply and its actual playback', () => {
    const { controller, handlers } = harness()
    const event = {
      message_id: 'message',
      conversation_id: 'conversation',
      task_id: 'reply-task',
      turn_id: 'reply-task',
      audio_data: 'audio',
      format: 'wav',
    }

    handlers.get(Events.CHAT.AUDIO_WITH_EXPRESSION)!(event)
    playback.playAudio.mock.calls.at(-1)?.[1].onStart()

    expect(document.getElementById('audioStatus')?.dataset.lastAudioTaskId).toBe(
      document.getElementById('livestreamStatus')?.dataset.lastBilibiliReplyId,
    )
    controller.dispose()
  })

  it('keeps singing playback hidden on live while preserving lip sync evidence', () => {
    const { controller, handlers, singingAudio } = harness()
    const complete = {
      task_id: 'sing-task',
      audio_url: '/api/singing/audio/song_final.wav',
      volumes: [0.1, 0.5],
      duration: 180,
      video_title: '测试歌曲',
      voice_name: 'shige_utage',
    }

    handlers.get(Events.SING.COMPLETE)!(complete)

    expect(document.getElementById('singingPlayer')).toBeNull()
    expect(singingAudio.hidden).toBe(true)
    expect(singingAudio.getAttribute('src')).toBe(complete.audio_url)
    expect(singingAudio.play).toHaveBeenCalledOnce()
    singingAudio.dispatchEvent(new Event('play'))
    expect(lipSync.startLipSync).toHaveBeenCalledWith(
      singingAudio,
      complete.volumes,
      expect.any(Function),
    )
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.lastAudioTaskId',
      'sing-task',
    )
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.lastAudioKind',
      'singing',
    )
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.playbackState',
      'playing',
    )

    singingAudio.dispatchEvent(new Event('ended'))
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.playbackState',
      'completed',
    )
    controller.dispose()
  })

  it('unlocks playback from a user gesture and releases every listener', () => {
    vi.clearAllMocks()
    const { bgm, controller, handlers, socket } = harness()
    const status = document.getElementById('audioStatus')!

    status.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))

    expect(playback.unlockAudioPlayback).toHaveBeenCalledOnce()
    expect(bgm.unlock).toHaveBeenCalledOnce()
    expect(status.hidden).toBe(true)
    expect(status.textContent).toBe('')
    controller.dispose()
    expect(handlers.size).toBe(0)
    expect(socket.off).toHaveBeenCalledTimes(6)
    expect(playback.stopAudio).toHaveBeenCalledOnce()
  })
})
