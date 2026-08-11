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

vi.mock('@/components/live2d/useAudioPlayback', () => playback)

function harness() {
  const handlers = new Map<string, (...args: unknown[]) => void>()
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
  document.body.innerHTML =
    '<span id="audioStatus" data-playback-state="idle" data-playback-count="0" hidden></span>'
  const controller = createLiveAudioController(socket, document)
  return { controller, handlers, socket }
}

describe('standalone live audio', () => {
  beforeEach(() => vi.clearAllMocks())

  it('routes complete and progressive TTS events through the shared player', () => {
    const { controller, handlers } = harness()
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

    expect(playback.playAudio).toHaveBeenCalledWith(complete, expect.any(Object))
    expect(playback.startAudioStream).toHaveBeenCalledWith(start, expect.any(Object))
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

  it('unlocks playback from a user gesture and releases every listener', () => {
    const { controller, handlers, socket } = harness()
    const status = document.getElementById('audioStatus')!

    status.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))

    expect(playback.unlockAudioPlayback).toHaveBeenCalledOnce()
    expect(status.hidden).toBe(true)
    expect(status.textContent).toBe('')
    controller.dispose()
    expect(handlers.size).toBe(0)
    expect(socket.off).toHaveBeenCalledTimes(5)
    expect(playback.stopAudio).toHaveBeenCalledOnce()
  })
})
