import { beforeEach, describe, expect, it, vi } from 'vitest'

const fixtures = vi.hoisted(() => {
  let beforeModelUpdate: (() => void) | null = null
  let applicationOptions: Record<string, unknown> | null = null
  const setParameterValueByIndex = vi.fn()
  const parameterNames = [
    'ParamMouthOpenY',
    'ParamAngleX',
    'ParamAngleY',
    'ParamAngleZ',
    'ParamBodyAngleX',
    'ParamBodyAngleY',
    'ParamBodyAngleZ',
    'ParamBreath',
  ]
  const parameterValues = Array.from({ length: parameterNames.length }, () => 0)
  const motionState: { currentGroup?: string } = { currentGroup: 'Idle' }
  const idleMotions = [{ setIsLoopFadeIn: vi.fn() }, { setIsLoopFadeIn: vi.fn() }]
  setParameterValueByIndex.mockImplementation((index: number, value: number) => {
    parameterValues[index] = value
  })
  const model = {
    width: 400,
    height: 800,
    scale: { x: 1, y: 1, set: vi.fn() },
    anchor: { set: vi.fn() },
    position: { set: vi.fn() },
    internalModel: {
      coreModel: {
        getParameterCount: vi.fn().mockReturnValue(parameterNames.length),
        getParameterIndex: vi.fn((name: string) => parameterNames.indexOf(name)),
        getParameterValueByIndex: vi.fn((index: number) => parameterValues[index]),
        getParameterDefaultValue: vi.fn((index: number) => (index === 1 ? 2 : 0)),
        getParameterMinimumValue: vi.fn((index: number) =>
          index === 7 ? 0 : parameterNames[index].startsWith('ParamBodyAngle') ? -10 : -30,
        ),
        getParameterMaximumValue: vi.fn((index: number) =>
          index === 7 ? 1 : parameterNames[index].startsWith('ParamBodyAngle') ? 10 : 30,
        ),
        setParameterValueByIndex,
      },
      motionManager: {
        state: motionState,
        groups: { idle: 'Idle' },
        definitions: { Idle: [{}, {}] },
        loadMotion: vi.fn((_group: string, index: number) => Promise.resolve(idleMotions[index])),
        stopAllMotions: vi.fn(),
      },
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
    idleMotions,
    setParameterValueByIndex,
    setApplicationOptions: (options: Record<string, unknown>) => {
      applicationOptions = options
    },
    resetModelState: () => {
      parameterValues.fill(0)
      motionState.currentGroup = 'Idle'
    },
    setParameterValue: (name: string, value: number) => {
      parameterValues[parameterNames.indexOf(name)] = value
    },
    getParameterValue: (name: string) => parameterValues[parameterNames.indexOf(name)],
    setMotionGroup: (group: string) => {
      motionState.currentGroup = group
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
    fixtures.resetModelState()
    document.body.innerHTML = `
      <canvas id="live2dCanvas"></canvas>
      <p id="modelStatus"></p>
      <span id="audioStatus" data-lip-sync-applied-count="0" data-lip-sync-peak="0"></span>
    `
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
    expect(fixtures.setParameterValueByIndex).toHaveBeenCalledWith(0, expect.any(Number))
    expect(notification.dataset.lipSync).toBe('observed')
    stage.dispose()
    stage.dispose()
  })

  it('applies production mouth targets inside the Live2D model frame', async () => {
    const { createLive2DStage } = await import('./live2d-stage')
    const socket = { on: vi.fn().mockReturnThis(), off: vi.fn().mockReturnThis() }
    const stage = createLive2DStage(socket)
    await stage.ready

    stage.setMouth(0.8, 'task-1')
    fixtures.emitBeforeModelUpdate()

    expect(fixtures.setParameterValueByIndex).toHaveBeenLastCalledWith(0, 0.8)
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.lastLipSyncTaskId',
      'task-1',
    )
    expect(document.getElementById('audioStatus')).toHaveProperty(
      'dataset.lipSyncAppliedCount',
      '1',
    )
    expect(Number(document.getElementById('audioStatus')?.dataset.lipSyncPeak)).toBe(0.8)
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

  it('keeps authored idle motion continuous when the same motion loops', async () => {
    const { createLive2DStage } = await import('./live2d-stage')
    const socket = { on: vi.fn().mockReturnThis(), off: vi.fn().mockReturnThis() }

    const stage = createLive2DStage(socket)
    await stage.ready

    expect(fixtures.idleMotions[0].setIsLoopFadeIn).toHaveBeenCalledWith(false)
    expect(fixtures.idleMotions[1].setIsLoopFadeIn).toHaveBeenCalledWith(false)
    stage.dispose()
  })

  it('amplifies idle motion without hitting hard parameter limits', async () => {
    const { createLive2DStage } = await import('./live2d-stage')
    const socket = { on: vi.fn().mockReturnThis(), off: vi.fn().mockReturnThis() }
    const stage = createLive2DStage(socket, { idleVitality: true })
    await stage.ready

    fixtures.setParameterValue('ParamAngleX', 8)
    fixtures.setParameterValue('ParamBodyAngleX', 4)
    fixtures.setParameterValue('ParamBreath', 0.9)
    fixtures.emitBeforeModelUpdate()

    expect(fixtures.getParameterValue('ParamAngleX')).toBeCloseTo(15.8)
    expect(fixtures.getParameterValue('ParamBodyAngleX')).toBeGreaterThan(9)
    expect(fixtures.getParameterValue('ParamBodyAngleX')).toBeLessThan(10)
    expect(fixtures.getParameterValue('ParamBreath')).toBeCloseTo(1, 3)

    fixtures.setMotionGroup('TapBody')
    fixtures.setParameterValue('ParamAngleX', 8)
    fixtures.emitBeforeModelUpdate()
    expect(fixtures.getParameterValue('ParamAngleX')).toBe(8)
    stage.dispose()
  })
})
