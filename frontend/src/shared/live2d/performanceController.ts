import {
  DEFAULT_LIVE2D_PERFORMANCE_PLAN,
  normalizeLive2DPerformancePlan,
  type Live2DPerformancePlanV1,
} from './performanceContract'
import { MAO_PERFORMANCE_PROFILE } from './maoPerformanceProfile'
import type { Live2DParameterAdapter, Live2DPerformanceProfile } from './performanceProfile'
import {
  dispatchLive2DPerformanceObservation,
  type Live2DPerformanceObserver,
} from './performanceObservability'

export type Live2DPerformanceState = 'calm' | 'armed' | 'speaking' | 'settling'

export { DEFAULT_LIVE2D_PERFORMANCE_PLAN } from './performanceContract'
const ACTIVATION_MS = 250
const SETTLING_MS = 350

export interface Live2DPerformanceControllerOptions extends Partial<Live2DParameterAdapter> {
  write: Live2DParameterAdapter['write']
  profile?: Live2DPerformanceProfile
  now?: () => number
  observe?: Live2DPerformanceObserver
}

export class Live2DPerformanceController {
  state: Live2DPerformanceState = 'calm'
  private readonly read: (name: string) => number
  private readonly write: (name: string, value: number) => void
  private readonly profile: Live2DPerformanceProfile
  private readonly now: () => number
  private readonly observe: Live2DPerformanceObserver
  private plan = DEFAULT_LIVE2D_PERFORMANCE_PLAN
  private taskId: string | null = null
  private phaseStartedAt = 0
  private destroyed = false
  private activationObserved = false

  constructor(options: Live2DPerformanceControllerOptions) {
    this.read = options.read ?? (() => 0)
    this.write = options.write
    this.profile = options.profile ?? MAO_PERFORMANCE_PROFILE
    this.now = options.now ?? (() => performance.now())
    this.observe = options.observe ?? dispatchLive2DPerformanceObservation
  }

  arm(plan: unknown, taskId: string): void {
    if (this.destroyed) return
    if (this.state === 'speaking' || this.state === 'settling') {
      this.apply(DEFAULT_LIVE2D_PERFORMANCE_PLAN, 0)
    }
    const normalized = normalizeLive2DPerformancePlan(plan)
    this.plan = normalized.plan
    this.taskId = taskId
    this.state = 'armed'
    this.activationObserved = false
    this.observe({
      kind: 'plan',
      source: this.plan.source,
      base: this.plan.base,
      accent: this.plan.accent,
      fallback: normalized.fallback,
    })
  }

  start(taskId: string): boolean {
    if (this.destroyed || this.state !== 'armed' || taskId !== this.taskId) return false
    this.state = 'speaking'
    this.phaseStartedAt = this.now()
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
    this.apply(DEFAULT_LIVE2D_PERFORMANCE_PLAN, 0)
  }

  tick(): void {
    if (this.destroyed || this.state === 'armed') return
    const elapsed = Math.max(0, this.now() - this.phaseStartedAt)
    if (this.state === 'speaking') {
      if (!this.activationObserved) {
        this.activationObserved = true
        this.observe({
          kind: 'activation_delay',
          source: this.plan.source,
          base: this.plan.base,
          accent: this.plan.accent,
          delayMs: elapsed,
        })
      }
      const expressionProgress = Math.min(1, elapsed / ACTIVATION_MS)
      this.apply(this.plan, expressionProgress)
      return
    }
    if (this.state === 'settling') {
      const remaining = Math.max(0, 1 - elapsed / SETTLING_MS)
      this.apply(this.plan, remaining)
      if (remaining === 0) this.resetToCalm()
      return
    }
    this.apply(DEFAULT_LIVE2D_PERFORMANCE_PLAN, 0)
  }

  destroy(): void {
    if (this.destroyed) return
    this.resetToCalm()
    this.apply(DEFAULT_LIVE2D_PERFORMANCE_PLAN, 0)
    this.destroyed = true
  }

  private apply(plan: Live2DPerformancePlanV1, expression: number): void {
    for (const parameter of this.profile.resolve(plan, expression)) {
      const value = Math.max(
        parameter.min,
        Math.min(parameter.max, this.read(parameter.name) + parameter.offset),
      )
      this.write(parameter.name, value)
    }
  }

  private resetToCalm(): void {
    this.state = 'calm'
    this.plan = DEFAULT_LIVE2D_PERFORMANCE_PLAN
    this.taskId = null
    this.phaseStartedAt = 0
    this.activationObserved = false
  }
}

export function createLive2DPerformanceController(
  adapter: Live2DParameterAdapter,
  options: Omit<Live2DPerformanceControllerOptions, keyof Live2DParameterAdapter> = {},
): Live2DPerformanceController {
  return new Live2DPerformanceController({ ...options, ...adapter })
}
