import { beforeEach, describe, expect, it, vi } from 'vitest'

const startLipSync = vi.hoisted(() => vi.fn())
const stopLipSync = vi.hoisted(() => vi.fn())
const setMouthTarget = vi.hoisted(() => vi.fn())
const setExpression = vi.hoisted(() => vi.fn())

vi.mock('./useLipSync', () => ({ setMouthTarget, startLipSync, stopLipSync }))
vi.mock('./useLive2DModel', () => ({ setExpression }))

class MockAudio {
  static instances: MockAudio[] = []

  currentTime = 0
  onended: (() => void) | null = null
  src = ''
  pause = vi.fn()
  load = vi.fn()
  play = vi.fn(() => Promise.resolve())

  constructor(src = '') {
    this.src = src
    MockAudio.instances.push(this)
  }

  removeAttribute(name: string): void {
    if (name === 'src') this.src = ''
  }
}

describe('useAudioPlayback', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    MockAudio.instances = []
    vi.stubGlobal('Audio', MockAudio)
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:qwen-audio'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
  })

  it('primes and reuses one audio element for delayed chat playback', async () => {
    const { playAudio, unlockAudioPlayback } = await import('./useAudioPlayback')

    unlockAudioPlayback()
    expect(MockAudio.instances).toHaveLength(1)
    expect(MockAudio.instances[0].play).toHaveBeenCalledTimes(1)

    await Promise.resolve()
    await Promise.resolve()
    playAudio({ audio_data: btoa('real qwen wav'), format: 'wav' })

    expect(MockAudio.instances).toHaveLength(1)
    expect(MockAudio.instances[0].src).toBe('blob:qwen-audio')
    expect(MockAudio.instances[0].play).toHaveBeenCalledTimes(2)
  })

  it('starts performance only after play resolves and completes it on audio end', async () => {
    const { playAudio } = await import('./useAudioPlayback')
    const lifecycle = {
      onStart: vi.fn(),
      onComplete: vi.fn(),
      onCancel: vi.fn(),
    }

    playAudio({ audio_data: btoa('qwen wav'), format: 'wav' }, lifecycle)
    expect(lifecycle.onStart).not.toHaveBeenCalled()

    await Promise.resolve()
    expect(lifecycle.onStart).toHaveBeenCalledTimes(1)
    MockAudio.instances[0].onended?.()
    expect(lifecycle.onComplete).toHaveBeenCalledTimes(1)
    expect(lifecycle.onCancel).not.toHaveBeenCalled()
  })

  it('routes a complete-audio mouth timeline to the active stage', async () => {
    const { playAudio } = await import('./useAudioPlayback')
    const stageMouthTarget = vi.fn()

    playAudio(
      { audio_data: btoa('qwen wav'), format: 'wav', volumes: [0.2, 0.8] },
      undefined,
      stageMouthTarget,
    )

    expect(startLipSync).toHaveBeenCalledWith(MockAudio.instances[0], [0.2, 0.8], stageMouthTarget)
  })
})
