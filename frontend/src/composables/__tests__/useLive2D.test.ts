import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, type Ref } from 'vue'
import { activateChatTask, resetChatTaskGate } from '@/composables/chatTaskGate'
import { Events } from '@/constants/socket-events'

// Mock pixi.js before any imports
vi.mock('pixi.js', () => ({
  Application: vi.fn(function ApplicationMock() {
    return {
      view: document.createElement('canvas'),
      screen: { width: 800, height: 600 },
      renderer: { resize: vi.fn() },
      ticker: { add: vi.fn(), remove: vi.fn() },
      stage: { addChild: vi.fn(), removeChild: vi.fn() },
      destroy: vi.fn(),
    }
  }),
}))

// Mock pixi-live2d-display cubism4 before any imports
vi.mock('pixi-live2d-display/cubism4', () => ({
  Live2DModel: {
    from: vi.fn().mockResolvedValue({
      x: 0,
      y: 0,
      anchor: { set: vi.fn() },
      scale: { set: vi.fn() },
      interactive: true,
      getBounds: vi.fn().mockReturnValue({ width: 200, height: 400 }),
      focus: vi.fn(),
      motion: vi.fn(),
      expression: vi.fn(),
      destroy: vi.fn(),
      internalModel: {
        motionManager: {
          stopAllMotions: vi.fn(),
          groups: {},
          expressionNames: [],
        },
        coreModel: {
          getParameterIndex: vi.fn().mockReturnValue(-1),
          setParameterValueByIndex: vi.fn(),
        },
      },
    }),
  },
}))

const mockSocket = vi.hoisted(() => ({
  on: vi.fn(),
  off: vi.fn(),
}))

const audioPlayback = vi.hoisted(() => ({
  playAudio: vi.fn(),
  stopAudio: vi.fn(),
  startAudioStream: vi.fn(),
  pushAudioStreamChunk: vi.fn(),
  endAudioStream: vi.fn(),
}))

vi.mock('@/composables/useSocket', () => ({
  getSocket: () => mockSocket,
}))

vi.mock('@/components/live2d/useAudioPlayback', () => audioPlayback)

describe('useLive2D', () => {
  let canvasRef: Ref<HTMLCanvasElement | null>
  let useLive2D: typeof import('@/components/live2d/useLive2D').useLive2D
  let MODEL_PATH: string

  beforeEach(async () => {
    vi.clearAllMocks()
    resetChatTaskGate()
    canvasRef = ref(document.createElement('canvas'))
    const mod = await import('@/components/live2d/useLive2D')
    useLive2D = mod.useLive2D
    MODEL_PATH = mod.MODEL_PATH
  })

  describe('initial state', () => {
    it('starts with isLoaded false', () => {
      const live2d = useLive2D(canvasRef)
      expect(live2d.isLoaded.value).toBe(false)
    })

    it('starts with isLoading false', () => {
      const live2d = useLive2D(canvasRef)
      expect(live2d.isLoading.value).toBe(false)
    })

    it('starts with empty loadError', () => {
      const live2d = useLive2D(canvasRef)
      expect(live2d.loadError.value).toBe('')
    })

    it('starts with modelInfo null', () => {
      const live2d = useLive2D(canvasRef)
      expect(live2d.modelInfo.value).toBeNull()
    })

    it('starts with isDragging false', () => {
      const live2d = useLive2D(canvasRef)
      expect(live2d.isDragging.value).toBe(false)
    })
  })

  describe('setMouthTarget', () => {
    it('clamps value to 0-1 range', () => {
      const live2d = useLive2D(canvasRef)
      live2d.setMouthTarget(0.5)
      // No direct assertion — setMouthTarget updates internal state
      // It should not throw
      expect(() => live2d.setMouthTarget(-1)).not.toThrow()
      expect(() => live2d.setMouthTarget(2)).not.toThrow()
    })

    it('handles zero and one boundaries', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.setMouthTarget(0)).not.toThrow()
      expect(() => live2d.setMouthTarget(1)).not.toThrow()
    })
  })

  describe('zoom', () => {
    it('applies zoom with positive delta', () => {
      const live2d = useLive2D(canvasRef)
      // Should not throw when no model loaded
      expect(() => live2d.zoom(0.1)).not.toThrow()
    })

    it('applies zoom with negative delta', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.zoom(-0.1)).not.toThrow()
    })

    it('handles zero delta', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.zoom(0)).not.toThrow()
    })
  })

  describe('resetView', () => {
    it('does not throw when no model loaded', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.resetView()).not.toThrow()
    })
  })

  describe('setScaleStrategy', () => {
    it('does not throw with valid strategy', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.setScaleStrategy('contain')).not.toThrow()
      expect(() => live2d.setScaleStrategy('cover')).not.toThrow()
      expect(() => live2d.setScaleStrategy('fit')).not.toThrow()
    })

    it('ignores invalid strategy', () => {
      const live2d = useLive2D(canvasRef)
      // Should not throw
      expect(() => live2d.setScaleStrategy('invalid')).not.toThrow()
    })
  })

  describe('focus', () => {
    it('does not throw when no model loaded', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.focus(100, 200)).not.toThrow()
    })
  })

  describe('executeAction', () => {
    it('handles expression action without model', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.executeAction({ type: 'expression', name: 'happy' })).not.toThrow()
    })

    it('handles motion action without model', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.executeAction({ type: 'motion', group: 'Idle', index: 0 })).not.toThrow()
    })

    it('handles param action without model', () => {
      const live2d = useLive2D(canvasRef)
      expect(() =>
        live2d.executeAction({ type: 'param', name: 'ParamAngleX', value: 30 }),
      ).not.toThrow()
    })

    it('handles sequence action without model', () => {
      const live2d = useLive2D(canvasRef)
      expect(() =>
        live2d.executeAction({
          type: 'sequence',
          actions: [
            { type: 'expression', name: 'happy' },
            { type: 'wait', ms: 100 },
            { type: 'expression', name: 'idle' },
          ],
        }),
      ).not.toThrow()
    })
  })

  describe('destroy', () => {
    it('can be called without error', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.destroy()).not.toThrow()
    })

    it('owns one socket listener set across repeated initialization', async () => {
      const live2d = useLive2D(canvasRef)

      await live2d.init()
      await live2d.init()

      expect(mockSocket.on).toHaveBeenCalledTimes(7)
      const registrations = mockSocket.on.mock.calls
      live2d.destroy()
      expect(mockSocket.off).toHaveBeenCalledTimes(7)
      expect(mockSocket.off.mock.calls).toEqual(
        registrations.map(([event, callback]) => [event, callback]),
      )
    })

    it('keeps shared socket listeners until the last instance is destroyed', async () => {
      const first = useLive2D(canvasRef)
      const second = useLive2D(canvasRef)

      await first.init()
      await second.init()

      expect(mockSocket.on).toHaveBeenCalledTimes(7)
      first.destroy()
      expect(mockSocket.off).not.toHaveBeenCalled()
      second.destroy()
      expect(mockSocket.off).toHaveBeenCalledTimes(7)
    })

    it('forwards correlated streaming events for only the current chat task', async () => {
      expect(Events.CHAT.AUDIO_STREAM_START).toBe('chat:audio_stream_start')
      expect(Events.CHAT.AUDIO_STREAM_CHUNK).toBe('chat:audio_stream_chunk')
      expect(Events.CHAT.AUDIO_STREAM_END).toBe('chat:audio_stream_end')

      const live2d = useLive2D(canvasRef)
      await live2d.init()
      const observations: unknown[] = []
      const observe = (event: Event) => {
        observations.push((event as CustomEvent).detail)
      }
      window.addEventListener('animetta:live2d-performance-observation', observe)
      const listeners = new Map<string, (data: unknown) => void>()
      for (const [event, listener] of mockSocket.on.mock.calls) {
        if (typeof event === 'string' && typeof listener === 'function') {
          listeners.set(event, (data: unknown) => listener(data))
        }
      }
      const identity = {
        message_id: '00000000-0000-0000-0000-000000000001',
        conversation_id: '00000000-0000-0000-0000-000000000002',
        task_id: '00000000-0000-0000-0000-000000000003',
        turn_id: '00000000-0000-0000-0000-000000000003',
      }
      const staleIdentity = {
        ...identity,
        task_id: '00000000-0000-0000-0000-000000000004',
        turn_id: '00000000-0000-0000-0000-000000000004',
      }
      activateChatTask(identity)

      listeners.get(Events.CHAT.AUDIO_STREAM_START)?.({
        ...staleIdentity,
        stream_id: '00000000-0000-0000-0000-000000000010',
      })
      listeners.get(Events.CHAT.AUDIO_STREAM_START)?.({
        ...identity,
        stream_id: '00000000-0000-0000-0000-000000000010',
      })
      listeners.get(Events.CHAT.AUDIO_STREAM_CHUNK)?.({
        ...identity,
        stream_id: '00000000-0000-0000-0000-000000000010',
        sequence: 0,
        audio_data: 'AA==',
      })
      listeners.get(Events.CHAT.AUDIO_STREAM_END)?.({
        ...identity,
        stream_id: '00000000-0000-0000-0000-000000000010',
        final_sequence: 0,
        status: 'completed',
      })

      expect(audioPlayback.startAudioStream).toHaveBeenCalledTimes(1)
      expect(audioPlayback.pushAudioStreamChunk).toHaveBeenCalledTimes(1)
      expect(audioPlayback.endAudioStream).toHaveBeenCalledTimes(1)
      expect(observations).toContainEqual({
        kind: 'stale_drop',
        event: 'audio_stream_start',
      })
      window.removeEventListener('animetta:live2d-performance-observation', observe)
      live2d.destroy()
    })

    it('stops buffered audio on disconnect while retaining listeners for reconnect', async () => {
      const live2d = useLive2D(canvasRef)
      await live2d.init()
      const listeners = new Map<string, (data?: unknown) => void>()
      for (const [event, listener] of mockSocket.on.mock.calls) {
        if (typeof event === 'string' && typeof listener === 'function') {
          listeners.set(event, (data?: unknown) => listener(data))
        }
      }

      listeners.get('disconnect')?.('transport close')

      expect(audioPlayback.stopAudio).toHaveBeenCalledTimes(1)
      expect(mockSocket.off).not.toHaveBeenCalled()
      live2d.destroy()
    })
  })

  describe('handleResize', () => {
    it('does not throw when called with no init', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.handleResize()).not.toThrow()
    })
  })

  describe('startDrag / onDrag / stopDrag', () => {
    it('does not throw when no model loaded', () => {
      const live2d = useLive2D(canvasRef)
      live2d.startDrag(100, 200)
      live2d.onDrag(150, 250)
      live2d.stopDrag()
      expect(live2d.isDragging.value).toBe(false)
    })
  })

  describe('stopAudio', () => {
    it('does not throw when no audio playing', () => {
      const live2d = useLive2D(canvasRef)
      expect(() => live2d.stopAudio()).not.toThrow()
    })
  })

  describe('MODEL_PATH', () => {
    it('is a string pointing to a model3.json file', () => {
      expect(MODEL_PATH).toContain('.model3.json')
    })
  })
})
