import type { Live2DPerformancePlanV1 } from '@/types/socket-events'
import { resolveHiyoriPerformanceParameters } from './hiyoriPerformanceProfile'

export type Live2DPerformanceState = 'calm' | 'armed' | 'speaking' | 'settling'

export const DEFAULT_LIVE2D_PERFORMANCE_PLAN: Live2DPerformancePlanV1 = {
  version: 1,
  base: 'calm',
  intensity: 'subtle',
  accent: 'none',
  source: 'fallback',
}
const ACTIVATION_MS = 250
const SETTLING_MS = 350
const ACCENT_MS = 700

export interface Live2DPerformanceControllerOptions {
  write: (name: string, value: number) => void
  now?: () => number
}

export class Live2DPerformanceController {
  state: Live2DPerformanceState = 'calm'
  accentRuns = 0
  private readonly write: (name: string, value: number) => void
  private readonly now: () => number
  private plan = DEFAULT_LIVE2D_PERFORMANCE_PLAN
  private taskId: string | null = null
  private phaseStartedAt = 0
  private destroyed = false
  private accentConsumed = false

  constructor(options: Live2DPerformanceControllerOptions) {
    this.write = options.write
    this.now = options.now ?? (() => performance.now())
  }

  arm(plan: Live2DPerformancePlanV1, taskId: string): void {
    if (this.destroyed) return
    if (this.state === 'speaking' || this.state === 'settling') {
      this.apply(DEFAULT_LIVE2D_PERFORMANCE_PLAN, 0, 0)
    }
    this.plan = plan
    this.taskId = taskId
    this.state = 'armed'
    this.accentConsumed = false
  }

  start(taskId: string): boolean {
    if (this.destroyed || this.state !== 'armed' || taskId !== this.taskId) return false
    this.state = 'speaking'
    this.phaseStartedAt = this.now()
    if (this.plan.accent !== 'none' && !this.accentConsumed) {
      this.accentConsumed = true
      this.accentRuns += 1
    }
    return true
  }

  finish(taskId: string): void {
    if (this.destroyed || taskId !== this.taskId || this.state !== 'speaking') return
    this.state = 'settling'
    this.phaseStartedAt = this.now()
  }

  cancel(): void {
    if (this.destroyed) return
    this.resetToCalm()
    this.apply(DEFAULT_LIVE2D_PERFORMANCE_PLAN, 0, 0)
  }

  tick(): void {
    if (this.destroyed || this.state === 'armed') return
    const elapsed = Math.max(0, this.now() - this.phaseStartedAt)
    if (this.state === 'speaking') {
      const expressionProgress = Math.min(1, elapsed / ACTIVATION_MS)
      const accentProgress =
        this.plan.accent === 'none' ? 0 : Math.max(0, 1 - Math.abs(elapsed / ACCENT_MS - 0.5) * 2)
      this.apply(this.plan, expressionProgress, accentProgress)
      return
    }
    if (this.state === 'settling') {
      const remaining = Math.max(0, 1 - elapsed / SETTLING_MS)
      this.apply(this.plan, remaining, 0)
      if (remaining === 0) this.resetToCalm()
      return
    }
    this.apply(DEFAULT_LIVE2D_PERFORMANCE_PLAN, 0, 0)
  }

  destroy(): void {
    if (this.destroyed) return
    this.resetToCalm()
    this.apply(DEFAULT_LIVE2D_PERFORMANCE_PLAN, 0, 0)
    this.destroyed = true
  }

  private apply(plan: Live2DPerformancePlanV1, expression: number, accent: number): void {
    for (const parameter of resolveHiyoriPerformanceParameters(plan, expression, accent)) {
      this.write(parameter.name, parameter.value)
    }
  }

  private resetToCalm(): void {
    this.state = 'calm'
    this.plan = DEFAULT_LIVE2D_PERFORMANCE_PLAN
    this.taskId = null
    this.phaseStartedAt = 0
    this.accentConsumed = false
  }
}
