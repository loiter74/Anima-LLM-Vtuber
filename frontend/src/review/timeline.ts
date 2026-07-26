import type { ReviewClock, ReviewSession, ScheduledAction } from './contracts'

const defaultClock: ReviewClock = {
  setTimeout(callback, delayMs) {
    return window.setTimeout(callback, delayMs)
  },
  clearTimeout(id) {
    window.clearTimeout(id)
  },
}

export function createTimelinePlayer<Action>(
  timeline: readonly ScheduledAction<Action>[],
  dispatch: (action: Action) => void,
  clock: ReviewClock = defaultClock,
): ReviewSession {
  const timerIds = new Set<number>()
  let started = false
  let disposed = false

  return {
    start(): void {
      if (started || disposed) return
      started = true
      for (const scheduled of timeline) {
        const timerId = clock.setTimeout(() => {
          timerIds.delete(timerId)
          if (!disposed) dispatch(scheduled.action)
        }, scheduled.atMs)
        timerIds.add(timerId)
      }
    },
    dispose(): void {
      if (disposed) return
      disposed = true
      for (const timerId of timerIds) clock.clearTimeout(timerId)
      timerIds.clear()
    },
  }
}
