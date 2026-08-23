export interface PerformanceSequenceOptions {
  length: number
  play(index: number): void
  interrupt(): void
  complete(): void
  interruptionDelayMs?: number
  transitionDelayMs?: number
}

export interface PerformanceSequenceRunner {
  start(): void
  advance(): void
  dispose(): void
}

export function createPerformanceSequenceRunner(
  options: PerformanceSequenceOptions,
): PerformanceSequenceRunner {
  const interruptionDelayMs = options.interruptionDelayMs ?? 650
  const transitionDelayMs = options.transitionDelayMs ?? 450
  let index = 0
  let timer: ReturnType<typeof globalThis.setTimeout> | null = null
  let disposed = false
  let interruptionExercised = false

  const schedule = (callback: () => void, delayMs: number): void => {
    if (timer !== null) globalThis.clearTimeout(timer)
    timer = globalThis.setTimeout(() => {
      timer = null
      if (!disposed) callback()
    }, delayMs)
  }
  const playCurrent = (): void => {
    if (disposed) return
    options.play(index)
    if (!interruptionExercised) {
      interruptionExercised = true
      schedule(() => {
        options.interrupt()
        schedule(playCurrent, transitionDelayMs)
      }, interruptionDelayMs)
    }
  }

  return {
    start: playCurrent,
    advance(): void {
      if (disposed) return
      index += 1
      if (index >= options.length) {
        options.complete()
        return
      }
      schedule(playCurrent, transitionDelayMs)
    },
    dispose(): void {
      if (disposed) return
      disposed = true
      if (timer !== null) globalThis.clearTimeout(timer)
      timer = null
    },
  }
}
