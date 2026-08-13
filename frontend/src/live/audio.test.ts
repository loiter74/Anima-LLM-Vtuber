import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Events } from '@/constants/socket-events'
import { createLiveAudioController } from './audio'
import type { LiveSocket } from './controller'
import { SINGING_PLAYBACK_STORAGE_KEY, writeSingingPlayback } from '@/singing/playback-sync'

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

vi.mock('@/components/live2d/useAudioPlayback', () => playback)
vi.mock('@/components/live2d/useLipSync', () => lipSync)

function harness(playResult: Promise<void> = Promise.resolve()) {
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
  const controller = createLiveAudioController(socket, document, setMouthTarget, bgm)
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
    handlers.get(Events.CHAT.STOP_AUDIO)!({})

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
