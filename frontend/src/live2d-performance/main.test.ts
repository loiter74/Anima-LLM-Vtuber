import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Live2DPerformancePlanV1 } from '@/types/socket-events'
import { PERFORMANCE_REVIEW_PLANS } from './catalog'
import { mountLive2DPerformanceReview } from './main'

describe('mountLive2DPerformanceReview', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = '<main class="live-shell"></main>'
  })

  it('plays every semantic plan in order and disposes idempotently', () => {
    const played: string[] = []
    let interruptions = 0
    const stage = {
      ready: Promise.resolve(),
      playReviewAudio(
        element: HTMLElement,
        _volumes: readonly number[],
        plan?: Live2DPerformancePlanV1,
      ) {
        if (!plan) throw new Error('missing plan')
        played.push(`${plan.base}:${plan.accent}`)
        element.dataset.lipSync = 'observed'
      },
      cancelReviewAudio() {
        interruptions += 1
      },
      dispose() {},
    }
    const params = new URLSearchParams({
      review: '1',
      live2dPerformance: '1',
      audio: 'http://127.0.0.1/review.wav',
    })
    const handle = mountLive2DPerformanceReview(document, params, stage, [0.5])
    const audio = handle?.element.querySelector<HTMLAudioElement>('#reviewAudio')

    vi.advanceTimersByTime(650)
    vi.advanceTimersByTime(450)
    for (let index = 1; index < PERFORMANCE_REVIEW_PLANS.length; index += 1) {
      audio?.dispatchEvent(new Event('ended'))
      vi.advanceTimersByTime(450)
    }
    audio?.dispatchEvent(new Event('ended'))

    expect(played).toEqual([
      'calm:none',
      ...PERFORMANCE_REVIEW_PLANS.map((plan) => `${plan.base}:${plan.accent}`),
    ])
    expect(interruptions).toBe(1)
    expect(handle?.element.dataset.interruption).toBe('observed')
    expect(handle?.element.dataset.complete).toBe('true')
    expect(handle?.element.dataset.currentBase).toBe('calm')
    handle?.dispose()
    handle?.dispose()
    expect(document.querySelector('.live2d-performance-review')).toBeNull()
    vi.useRealTimers()
  })
})
