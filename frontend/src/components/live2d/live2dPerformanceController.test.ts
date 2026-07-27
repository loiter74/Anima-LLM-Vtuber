import { describe, expect, it, vi } from 'vitest'
import type { Live2DPerformancePlanV1 } from '@/types/socket-events'
import {
  HIYORI_PERFORMANCE_OWNED_PARAMETERS,
  resolveHiyoriPerformanceParameters,
} from './hiyoriPerformanceProfile'
import { Live2DPerformanceController } from './live2dPerformanceController'

const THINKING: Live2DPerformancePlanV1 = {
  version: 1,
  base: 'thinking',
  intensity: 'medium',
  accent: 'skeptical',
  source: 'llm',
}

describe('Live2DPerformanceController', () => {
  it('moves through calm, armed, speaking, settling and back to calm', () => {
    let now = 0
    const write = vi.fn()
    const controller = new Live2DPerformanceController({ write, now: () => now })

    expect(controller.state).toBe('calm')
    controller.arm(THINKING, 'task-1')
    expect(controller.state).toBe('armed')
    expect(controller.start('stale-task')).toBe(false)

    expect(controller.start('task-1')).toBe(true)
    expect(controller.state).toBe('speaking')
    now = 250
    controller.tick()
    expect(write).toHaveBeenCalled()
    expect(controller.accentRuns).toBe(1)

    controller.finish('task-1')
    expect(controller.state).toBe('settling')
    now = 600
    controller.tick()
    expect(controller.state).toBe('calm')
  })

  it('runs one accent only and ignores stale completion', () => {
    let now = 0
    const controller = new Live2DPerformanceController({ write: vi.fn(), now: () => now })
    controller.arm(THINKING, 'task-1')
    controller.start('task-1')
    for (now = 0; now <= 1000; now += 50) controller.tick()

    expect(controller.accentRuns).toBe(1)
    controller.finish('task-2')
    expect(controller.state).toBe('speaking')
  })

  it('returns to calm before arming a replacement task', () => {
    const write = vi.fn()
    const controller = new Live2DPerformanceController({ write })
    controller.arm(THINKING, 'task-1')
    controller.start('task-1')
    controller.tick()
    write.mockClear()

    controller.arm({ ...THINKING, base: 'cheerful' }, 'task-2')

    expect(controller.state).toBe('armed')
    expect(write).toHaveBeenCalled()
    expect(controller.start('task-1')).toBe(false)
  })

  it('interrupts immediately to calm and destroy is idempotent', () => {
    const write = vi.fn()
    const controller = new Live2DPerformanceController({ write })
    controller.arm(THINKING, 'task-1')
    controller.start('task-1')

    controller.cancel()
    expect(controller.state).toBe('calm')
    controller.destroy()
    controller.destroy()
    expect(controller.state).toBe('calm')
  })
})

describe('Hiyori performance profile', () => {
  it('never owns mouth opening and resolves deterministically without randomness', () => {
    const random = vi.spyOn(Math, 'random')
    const first = resolveHiyoriPerformanceParameters(THINKING, 1, 1)
    const second = resolveHiyoriPerformanceParameters(THINKING, 1, 1)

    expect(HIYORI_PERFORMANCE_OWNED_PARAMETERS).not.toContain('ParamMouthOpenY')
    expect(first).toEqual(second)
    expect(random).not.toHaveBeenCalled()
    random.mockRestore()
  })

  it('keeps every resolved value inside its declared bounds', () => {
    const values = resolveHiyoriPerformanceParameters(THINKING, 1, 1)

    for (const parameter of values) {
      expect(parameter.value).toBeGreaterThanOrEqual(parameter.min)
      expect(parameter.value).toBeLessThanOrEqual(parameter.max)
    }
  })

  it('references only parameters declared by Hiyori', async () => {
    const display = await import('../../../public/live2d/hiyori/Hiyori.cdi3.json')
    const available = new Set(display.default.Parameters.map((parameter) => parameter.Id))

    expect(HIYORI_PERFORMANCE_OWNED_PARAMETERS.every((name) => available.has(name))).toBe(true)
  })
})
