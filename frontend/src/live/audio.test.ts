import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Events } from '@/constants/socket-events'
import { createLiveAudioController } from './audio'
import type { LiveSocket } from './controller'

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

function harness() {
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
    <section id="singingPlayer" data-state="idle" hidden>
      <h2 id="singingTitle"></h2>
      <p id="singingIdentity"></p>
      <button id="singingPlayButton" type="button">播放</button>
      <audio id="singingAudio"></audio>
      <p id="singingPlaybackStatus"></p>
    </section>
  `
  const singingAudio = document.getElementById('singingAudio') as HTMLAudioElement
  vi.spyOn(singingAudio, 'play').mockResolvedValue()
  vi.spyOn(singingAudio, 'pause').mockImplementation(() => undefined)
  vi.spyOn(singingAudio, 'load').mockImplementation(() => undefined)
  const controller = createLiveAudioController(socket, document, setMouthTarget)
  return { controller, handlers, setMouthTarget, singingAudio, socket }
}

describe('standalone live audio', () => {
  beforeEach(() => vi.clearAllMocks())

  it('routes complete and progressive TTS events through the shared player', () => {
    const { controller, handlers, setMouthTarget } = harness()
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

    expect(playback.playAudio).toHaveBeenCalledWith(complete, expect.any(Object), setMouthTarget)
    expect(playback.startAudioStream).toHaveBeenCalledWith(
      start,
      expect.any(Object),
      setMouthTarget,
    )
    expect(playback.pushAudioStreamChunk).toHaveBeenCalledWith(chunk)
    expect(playback.endAudioStream).toHaveBeenCalledWith(end)
    expect(playback.stopAudio).toHaveBeenCalledOnce()

    const lifecycle = playback.playAudio.mock.calls[0][1]
    lifecycle.onStart()
    expect(document.getElementById('audioStatus')).toHaveProperty('dataset.playbackCount', '1')
    expect(document.getElementById('audioStatus')).toHaveProperty('dataset.lastAudioTaskId', 'task')
    lifecycle.onComplete()
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.playbackState',
      'completed',
    )
    controller.dispose()
  })

  it('exposes completed singing audio in a visible replayable player', () => {
    const { controller, handlers, setMouthTarget, singingAudio } = harness()
    const complete = {
      task_id: 'sing-task',
      audio_url: '/api/singing/audio/song_final.wav',
      volumes: [0.1, 0.5],
      video_title: '测试歌曲',
      voice_name: 'shige_utage',
    }

    handlers.get(Events.SING.COMPLETE)!(complete)

    expect(document.getElementById('singingPlayer')).toHaveProperty('hidden', false)
    expect(singingAudio.getAttribute('src')).toBe(complete.audio_url)
    expect(document.getElementById('singingTitle')?.textContent).toBe('测试歌曲')
    expect(document.getElementById('singingIdentity')?.textContent).toContain('shige_utage')
    expect(singingAudio.play).toHaveBeenCalledOnce()
    singingAudio.dispatchEvent(new Event('play'))
    expect(lipSync.startLipSync).toHaveBeenCalledWith(
      singingAudio,
      complete.volumes,
      setMouthTarget,
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
    expect(document.getElementById('singingPlaybackStatus')?.textContent).toBe(
      '播放完成，可重新播放',
    )
    expect(document.getElementById('singingPlayButton')?.textContent).toBe('重播')
    controller.dispose()
  })

  it('unlocks playback from a user gesture and releases every listener', () => {
    const { controller, handlers, socket } = harness()
    const status = document.getElementById('audioStatus')!

    status.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))

    expect(playback.unlockAudioPlayback).toHaveBeenCalledOnce()
    expect(status.hidden).toBe(true)
    expect(status.textContent).toBe('')
    controller.dispose()
    expect(handlers.size).toBe(0)
    expect(socket.off).toHaveBeenCalledTimes(6)
    expect(playback.stopAudio).toHaveBeenCalledOnce()
  })
})
