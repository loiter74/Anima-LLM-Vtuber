import { describe, expect, it, vi } from 'vitest'
import type { Live2DPerformancePlanV1 } from '@/types/socket-events'
import {
  MAO_PERFORMANCE_OWNED_PARAMETERS,
  resolveMaoPerformanceParameters,
} from './maoPerformanceProfile'
import { Live2DPerformanceController } from './live2dPerformanceController'

const ANNOYED: Live2DPerformancePlanV1 = {
  version: 1,
  base: 'annoyed',
  intensity: 'medium',
  accent: 'none',
  source: 'llm',
}

describe('Live2DPerformanceController', () => {
  it('falls back to calm when a wire plan contains an unknown semantic', () => {
    let now = 0
    const write = vi.fn()
    const observe = vi.fn()
    const controller = new Live2DPerformanceController({ write, now: () => now, observe })
    const invalidPlan = { ...ANNOYED, base: 'future-semantic' }

    controller.arm(invalidPlan as Live2DPerformancePlanV1, 'task-invalid')
    controller.start('task-invalid')
    now = 250

    expect(() => controller.tick()).not.toThrow()
    expect(write.mock.calls.every(([, value]) => Number.isFinite(value))).toBe(true)
    expect(observe).toHaveBeenNthCalledWith(1, {
      kind: 'plan',
      source: 'fallback',
      base: 'calm',
      accent: 'none',
      fallback: 'invalid_payload',
    })
  })

  it('observes audio-to-first-expression delay once with bounded labels', () => {
    let now = 0
    const observe = vi.fn()
    const controller = new Live2DPerformanceController({
      write: vi.fn(),
      now: () => now,
      observe,
    })

    controller.arm(ANNOYED, 'task-observed')
    controller.start('task-observed')
    now = 12
    controller.tick()
    now = 24
    controller.tick()

    expect(observe).toHaveBeenCalledTimes(2)
    expect(observe).toHaveBeenNthCalledWith(1, {
      kind: 'plan',
      source: 'llm',
      base: 'annoyed',
      accent: 'none',
      fallback: 'none',
    })
    expect(observe).toHaveBeenNthCalledWith(2, {
      kind: 'activation_delay',
      source: 'llm',
      base: 'annoyed',
      accent: 'none',
      delayMs: 12,
    })
  })

  it('maps deprecated wire semantics into the reduced catalog', () => {
    const observe = vi.fn()
    const controller = new Live2DPerformanceController({ write: vi.fn(), observe })

    controller.arm(
      { ...ANNOYED, base: 'thinking', accent: 'skeptical', source: 'llm' },
      'task-legacy',
    )

    expect(observe).toHaveBeenCalledWith({
      kind: 'plan',
      source: 'legacy',
      base: 'calm',
      accent: 'none',
      fallback: 'none',
    })
  })

  it('moves through calm, armed, speaking, settling and back to calm', () => {
    let now = 0
    const write = vi.fn()
    const controller = new Live2DPerformanceController({ write, now: () => now })

    expect(controller.state).toBe('calm')
    controller.arm(ANNOYED, 'task-1')
    expect(controller.state).toBe('armed')
    expect(controller.start('stale-task')).toBe(false)

    expect(controller.start('task-1')).toBe(true)
    expect(controller.state).toBe('speaking')
    now = 250
    controller.tick()
    expect(write).toHaveBeenCalled()

    controller.finish('task-1')
    expect(controller.state).toBe('settling')
    now = 600
    controller.tick()
    expect(controller.state).toBe('calm')
  })

  it('leaves motion-authored face parameters untouched while calm', () => {
    let now = 0
    const write = vi.fn()
    const controller = new Live2DPerformanceController({
      read: () => 0.4,
      write,
      now: () => now,
    })

    controller.arm(
      { version: 1, base: 'calm', intensity: 'subtle', accent: 'none', source: 'llm' },
      'task-calm',
    )
    controller.start('task-calm')
    now = 250
    controller.tick()

    expect(write).not.toHaveBeenCalled()
  })

  it('adds expression offsets to the current motion-authored parameter values', () => {
    let now = 0
    const write = vi.fn()
    const controller = new Live2DPerformanceController({
      read: (name) => (name === 'ParamMouthDown' ? 0.2 : 0),
      write,
      now: () => now,
    })

    controller.arm(ANNOYED, 'task-annoyed')
    controller.start('task-annoyed')
    now = 250
    controller.tick()

    expect(write).toHaveBeenCalledWith('ParamMouthDown', 0.42000000000000004)
    expect(write.mock.calls.some(([name]) => name === 'ParamEyeBallY')).toBe(false)
  })

  it('resolves parameters through the injected model profile', () => {
    let now = 0
    const write = vi.fn()
    const profile = {
      resolve: vi.fn(() => [{ name: 'ParamBrowLY', offset: 0.2, min: -1, max: 1 }]),
    }
    const controller = new Live2DPerformanceController({
      write,
      now: () => now,
      profile,
    })

    controller.arm(ANNOYED, 'task-profile')
    controller.start('task-profile')
    now = 250
    controller.tick()

    expect(profile.resolve).toHaveBeenCalledWith(ANNOYED, 1)
    expect(write).toHaveBeenCalledWith('ParamBrowLY', 0.2)
  })

  it('ignores stale completion', () => {
    let now = 0
    const controller = new Live2DPerformanceController({ write: vi.fn(), now: () => now })
    controller.arm(ANNOYED, 'task-1')
    controller.start('task-1')
    for (now = 0; now <= 1000; now += 50) controller.tick()

    controller.finish('task-2')
    expect(controller.state).toBe('speaking')
  })

  it('returns to calm before arming a replacement task', () => {
    const write = vi.fn()
    const controller = new Live2DPerformanceController({ write })
    controller.arm(ANNOYED, 'task-1')
    controller.start('task-1')
    controller.tick()
    write.mockClear()

    controller.arm({ ...ANNOYED, base: 'cheerful' }, 'task-2')

    expect(controller.state).toBe('armed')
    expect(write).not.toHaveBeenCalled()
    expect(controller.start('task-1')).toBe(false)
  })

  it('interrupts immediately to calm and destroy is idempotent', () => {
    const write = vi.fn()
    const controller = new Live2DPerformanceController({ write })
    controller.arm(ANNOYED, 'task-1')
    controller.start('task-1')

    controller.cancel()
    expect(controller.state).toBe('calm')
    controller.destroy()
    controller.destroy()
    expect(controller.state).toBe('calm')
  })
})

describe('Mao performance profile', () => {
  it('never owns mouth opening and resolves deterministically without randomness', () => {
    const random = vi.spyOn(Math, 'random')
    const first = resolveMaoPerformanceParameters(ANNOYED, 1)
    const second = resolveMaoPerformanceParameters(ANNOYED, 1)

    expect(MAO_PERFORMANCE_OWNED_PARAMETERS).not.toContain('ParamA')
    expect(first).toEqual(second)
    expect(random).not.toHaveBeenCalled()
    random.mockRestore()
  })

  it('keeps every resolved offset within its declared parameter span', () => {
    const values = resolveMaoPerformanceParameters(ANNOYED, 1)

    for (const parameter of values) {
      expect(Math.abs(parameter.offset)).toBeLessThanOrEqual(parameter.max - parameter.min)
    }
  })

  it('references only parameters declared by Mao', async () => {
    const display = await import('../../../public/live2d/mao/Mao.cdi3.json')
    const available = new Set(display.default.Parameters.map((parameter) => parameter.Id))

    expect(MAO_PERFORMANCE_OWNED_PARAMETERS.every((name) => available.has(name))).toBe(true)
  })
})
