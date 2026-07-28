import { afterEach, describe, expect, it, vi } from 'vitest'
import { parsePerformanceSamples } from './performanceSamples'
import { createPerformanceSequenceRunner } from './performanceSequence'

afterEach(() => {
  vi.useRealTimers()
})

describe('performance sample contract', () => {
  it('returns samples in canonical order regardless of input order', () => {
    const samples = parsePerformanceSamples(
      JSON.stringify([
        { base: 'surprised', audio: '/surprised.wav', mouthTimeline: [0.9] },
        { base: 'calm', audio: '/calm.wav', mouthTimeline: [0.1] },
        { base: 'annoyed', audio: '/annoyed.wav', mouthTimeline: [0.5] },
      ]),
    )

    expect(samples.map(({ base }) => base)).toEqual(['calm', 'annoyed', 'surprised'])
  })

  it('rejects duplicate or incomplete catalogs', () => {
    const duplicate = JSON.stringify([
      { base: 'calm', audio: '/one.wav', mouthTimeline: [0.1] },
      { base: 'calm', audio: '/two.wav', mouthTimeline: [0.2] },
      { base: 'surprised', audio: '/three.wav', mouthTimeline: [0.3] },
    ])

    expect(() => parsePerformanceSamples(duplicate)).toThrow('Invalid performance sample: calm')
  })
})

describe('performance sequence runner', () => {
  it('runs one interruption, advances in order, and stops all timers on dispose', () => {
    vi.useFakeTimers()
    const play = vi.fn()
    const interrupt = vi.fn()
    const complete = vi.fn()
    const runner = createPerformanceSequenceRunner({
      length: 3,
      play,
      interrupt,
      complete,
    })

    runner.start()
    expect(play).toHaveBeenCalledWith(0)
    vi.advanceTimersByTime(650)
    expect(interrupt).toHaveBeenCalledOnce()
    vi.advanceTimersByTime(450)
    expect(play).toHaveBeenNthCalledWith(2, 0)

    runner.advance()
    vi.advanceTimersByTime(450)
    expect(play).toHaveBeenNthCalledWith(3, 1)
    runner.advance()
    vi.advanceTimersByTime(450)
    expect(play).toHaveBeenNthCalledWith(4, 2)
    runner.advance()
    expect(complete).toHaveBeenCalledOnce()

    runner.dispose()
    runner.dispose()
    vi.runAllTimers()
    expect(play).toHaveBeenCalledTimes(4)
  })
})
