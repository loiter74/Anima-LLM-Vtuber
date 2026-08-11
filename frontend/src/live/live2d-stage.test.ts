import { beforeEach, describe, expect, it, vi } from 'vitest'

const fixtures = vi.hoisted(() => {
  let beforeModelUpdate: (() => void) | null = null
  let applicationOptions: Record<string, unknown> | null = null
  const setParameterValueByIndex = vi.fn()
  const model = {
    width: 400,
    height: 800,
    scale: { x: 1, y: 1, set: vi.fn() },
    anchor: { set: vi.fn() },
    position: { set: vi.fn() },
    internalModel: {
      coreModel: {
        getParameterCount: vi.fn().mockReturnValue(2),
        getParameterIndex: vi.fn().mockReturnValue(1),
        setParameterValueByIndex,
      },
      motionManager: { stopAllMotions: vi.fn() },
      on: vi.fn((_event: string, listener: () => void) => {
        beforeModelUpdate = listener
      }),
      off: vi.fn(),
    },
    expression: vi.fn(),
    motion: vi.fn().mockResolvedValue(undefined),
    destroy: vi.fn(),
  }
  return {
    model,
    setParameterValueByIndex,
    setApplicationOptions: (options: Record<string, unknown>) => {
      applicationOptions = options
    },
    getApplicationOptions: () => applicationOptions,
    emitBeforeModelUpdate: () => beforeModelUpdate?.(),
  }
})

vi.mock('pixi.js', () => ({
  Application: class {
    screen = { width: 1080, height: 1920 }
    stage = { addChild: vi.fn() }
    stop = vi.fn()
    destroy = vi.fn()
    constructor(options: Record<string, unknown>) {
      fixtures.setApplicationOptions(options)
    }
  },
}))
vi.mock('pixi-live2d-display/cubism4', () => ({
  Live2DModel: { from: vi.fn().mockResolvedValue(fixtures.model) },
}))

describe('createLive2DStage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = '<canvas id="live2dCanvas"></canvas><p id="modelStatus"></p>'
  })

  it('owns the only review playback and samples mouth volume in the model frame', async () => {
    const { createLive2DStage } = await import('./live2d-stage')
    const socket = { on: vi.fn().mockReturnThis(), off: vi.fn().mockReturnThis() }
    const stage = createLive2DStage(socket)
    await stage.ready
    const notification = document.createElement('aside')
    const audio = document.createElement('audio')
    audio.id = 'reviewAudio'
    Object.defineProperties(audio, {
      currentTime: { value: 0, writable: true },
      paused: { value: false },
      ended: { value: false },
    })
    const play = vi.spyOn(audio, 'play').mockResolvedValue()
    notification.append(audio)

    stage.playReviewAudio(
      notification,
      Array.from({ length: 10 }, () => 0.8),
    )
    fixtures.emitBeforeModelUpdate()

    expect(play).toHaveBeenCalledOnce()
    expect(fixtures.setParameterValueByIndex).toHaveBeenCalledWith(1, expect.any(Number))
    expect(notification.dataset.lipSync).toBe('observed')
    stage.dispose()
    stage.dispose()
  })

  it('applies production mouth targets inside the Live2D model frame', async () => {
    const { createLive2DStage } = await import('./live2d-stage')
    const socket = { on: vi.fn().mockReturnThis(), off: vi.fn().mockReturnThis() }
    const stage = createLive2DStage(socket)
    await stage.ready

    stage.setMouth(0.8)
    fixtures.emitBeforeModelUpdate()

    expect(fixtures.setParameterValueByIndex).toHaveBeenLastCalledWith(1, 0.8)
    stage.dispose()
  })

  it('can size the shared stage to a bounded broadcast avatar container', async () => {
    const { createLive2DStage } = await import('./live2d-stage')
    const socket = { on: vi.fn().mockReturnThis(), off: vi.fn().mockReturnThis() }
    const avatarContainer = document.createElement('section')

    const stage = createLive2DStage(socket, { resizeTo: avatarContainer })
    await stage.ready

    expect(fixtures.getApplicationOptions()?.resizeTo).toBe(avatarContainer)
    stage.dispose()
  })
})
