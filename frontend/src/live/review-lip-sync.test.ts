import { describe, expect, it, vi } from 'vitest'
import {
  bindReviewMouthAfterMotion,
  createReviewVolumeTimelineLipSync,
  parseReviewMouthTimeline,
} from './review-lip-sync'

describe('OBS review lip sync', () => {
  it('accepts only a bounded normalized 20ms mouth timeline', () => {
    expect(parseReviewMouthTimeline('[0,0.25,1]')).toEqual([0, 0.25, 1])
    expect(() => parseReviewMouthTimeline('[]')).toThrow(/mouth timeline/i)
    expect(() => parseReviewMouthTimeline('[1.1]')).toThrow(/mouth timeline/i)
    expect(() => parseReviewMouthTimeline(JSON.stringify(Array(3001).fill(0.5)))).toThrow(
      /mouth timeline/i,
    )
  })

  it('interpolates the mouth from a 60ms-advanced audio time and resets it when stopped', () => {
    const frames: FrameRequestCallback[] = []
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      frames.push(callback)
      return 7
    })
    const cancelFrame = vi.fn()
    const setMouth = vi.fn()
    const onObserved = vi.fn()
    const audio = {
      currentTime: 0,
      paused: false,
      ended: false,
    } as HTMLAudioElement
    const lipSync = createReviewVolumeTimelineLipSync({
      audio,
      volumes: [0, 0, 0.4, 0.8],
      setMouth,
      onObserved,
      requestFrame,
      cancelFrame,
    })

    lipSync.start()
    expect(setMouth.mock.calls.at(-1)?.[0]).toBeGreaterThan(0.77)
    expect(setMouth.mock.calls.at(-1)?.[0]).toBeLessThan(0.79)
    expect(onObserved).toHaveBeenCalledOnce()

    audio.currentTime = 99
    frames.at(-1)?.(20)
    expect(setMouth.mock.calls.at(-1)?.[0]).toBeGreaterThanOrEqual(0)
    expect(setMouth.mock.calls.at(-1)?.[0]).toBeLessThanOrEqual(1)

    lipSync.stop()
    expect(cancelFrame).toHaveBeenCalledWith(7)
    expect(setMouth).toHaveBeenLastCalledWith(0)
  })

  it('keeps low speech frames visible without turning silence into mouth movement', () => {
    const setMouth = vi.fn()
    const lipSync = createReviewVolumeTimelineLipSync({
      audio: {
        currentTime: 0,
        paused: false,
        ended: false,
      } as HTMLAudioElement,
      volumes: [0, 0, 0.2, 0.2],
      setMouth,
      requestFrame: vi.fn(() => 1),
      cancelFrame: vi.fn(),
    })

    lipSync.start()
    expect(setMouth.mock.calls.at(-1)?.[0]).toBeGreaterThan(0.3)
  })

  it('returns the mouth to zero while paused or ended', () => {
    const frames: FrameRequestCallback[] = []
    const setMouth = vi.fn()
    const audioState = {
      currentTime: 0,
      paused: true,
      ended: false,
    }
    const audio = audioState as HTMLAudioElement
    const lipSync = createReviewVolumeTimelineLipSync({
      audio,
      volumes: [1, 1, 1, 1],
      setMouth,
      requestFrame: (callback) => {
        frames.push(callback)
        return frames.length
      },
      cancelFrame: vi.fn(),
    })

    lipSync.start()
    expect(setMouth).toHaveBeenLastCalledWith(0)

    audioState.paused = false
    audioState.ended = true
    frames.at(-1)?.(20)
    expect(setMouth).toHaveBeenLastCalledWith(0)
  })

  it('writes the latest mouth value after motion updates and before model commit', () => {
    const beforeModelUpdates: Array<() => void> = []
    const coreModel = {
      getParameterCount: vi.fn(() => 64),
      getParameterIndex: vi.fn((name: string) => (name === 'ParamA' ? 12 : 100)),
      setParameterValueByIndex: vi.fn(),
    }
    const internalModel = {
      coreModel,
      on: vi.fn((_event: 'beforeModelUpdate', listener: () => void) => {
        beforeModelUpdates.push(listener)
      }),
      off: vi.fn(),
    }
    const onApplied = vi.fn()

    const binding = bindReviewMouthAfterMotion(internalModel, onApplied)
    binding.setMouth(0.8)
    expect(coreModel.setParameterValueByIndex).not.toHaveBeenCalled()

    beforeModelUpdates[0]?.()
    expect(coreModel.getParameterIndex).toHaveBeenCalledWith('ParamA')
    expect(coreModel.setParameterValueByIndex).toHaveBeenLastCalledWith(12, 0.8)
    expect(onApplied).toHaveBeenCalledOnce()

    binding.dispose()
    expect(internalModel.off).toHaveBeenCalledWith('beforeModelUpdate', beforeModelUpdates[0])
  })

  it('samples the current audio time inside the same Live2D model update without a second RAF', () => {
    const beforeModelUpdates: Array<() => void> = []
    const requestFrame = vi.fn(() => 7)
    const coreModel = {
      getParameterCount: vi.fn(() => 13),
      getParameterIndex: vi.fn(() => 12),
      setParameterValueByIndex: vi.fn(),
    }
    const binding = bindReviewMouthAfterMotion({
      coreModel,
      on: vi.fn((_event: 'beforeModelUpdate', listener: () => void) => {
        beforeModelUpdates.push(listener)
      }),
      off: vi.fn(),
    })
    const audioState = {
      currentTime: 0,
      paused: false,
      ended: false,
    }
    const lipSync = createReviewVolumeTimelineLipSync({
      audio: audioState as HTMLAudioElement,
      volumes: [0, 0, 0.4, 0.8, 1],
      setMouth: binding.setMouth,
      manualSampling: true,
      requestFrame,
      cancelFrame: vi.fn(),
    })
    binding.setBeforeApply(lipSync.sample)

    lipSync.start()
    audioState.currentTime = 0.02
    beforeModelUpdates[0]?.()

    expect(requestFrame).not.toHaveBeenCalled()
    expect(coreModel.setParameterValueByIndex.mock.calls.at(-1)?.[1]).toBeGreaterThan(0)
  })
})
