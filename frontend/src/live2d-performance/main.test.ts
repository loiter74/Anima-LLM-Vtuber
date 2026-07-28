import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Live2DPerformancePlanV1 } from '@/types/socket-events'
import { PERFORMANCE_ACCENTS, PERFORMANCE_BASES, PERFORMANCE_REVIEW_PLANS } from './catalog'
import { mountLive2DPerformanceReview } from './main'

describe('mountLive2DPerformanceReview', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = '<main class="live-shell"></main>'
  })

  it('plays every semantic plan in order and disposes idempotently', () => {
    const played: Array<{ plan: string; audio: string; volumes: readonly number[] }> = []
    let interruptions = 0
    const stage = {
      ready: Promise.resolve(),
      playReviewAudio(
        element: HTMLElement,
        volumes: readonly number[],
        plan?: Live2DPerformancePlanV1,
      ) {
        if (!plan) throw new Error('missing plan')
        const audio = element.querySelector<HTMLAudioElement>('#reviewAudio')
        played.push({
          plan: `${plan.base}:${plan.accent}`,
          audio: audio?.src ?? '',
          volumes,
        })
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
      performanceSamples: JSON.stringify([
        {
          base: 'calm',
          audio: 'http://127.0.0.1/calm.wav',
          mouthTimeline: [0.1],
        },
        {
          base: 'annoyed',
          audio: 'http://127.0.0.1/annoyed.wav',
          mouthTimeline: [0.5],
        },
        {
          base: 'surprised',
          audio: 'http://127.0.0.1/surprised.wav',
          mouthTimeline: [0.9],
        },
      ]),
    })
    const handle = mountLive2DPerformanceReview(document, params, stage)
    const audio = handle?.element.querySelector<HTMLAudioElement>('#reviewAudio')

    expect(handle?.element.hidden).toBe(true)
    expect(handle?.element.textContent).toBe('')
    expect(document.querySelector('.live2d-performance-review:not([hidden])')).toBeNull()

    window.dispatchEvent(
      new CustomEvent('animetta:live2d-performance-observation', {
        detail: {
          kind: 'activation_delay',
          source: 'llm',
          base: 'calm',
          accent: 'none',
          delayMs: 12,
        },
      }),
    )
    expect(handle?.element.dataset.activationObserved).toBe('true')

    vi.advanceTimersByTime(650)
    vi.advanceTimersByTime(450)
    for (let index = 1; index < PERFORMANCE_REVIEW_PLANS.length; index += 1) {
      audio?.dispatchEvent(new Event('ended'))
      vi.advanceTimersByTime(450)
    }
    audio?.dispatchEvent(new Event('ended'))

    expect(played.map(({ plan }) => plan)).toEqual([
      'calm:none',
      ...PERFORMANCE_REVIEW_PLANS.map((plan) => `${plan.base}:${plan.accent}`),
    ])
    expect(played.map(({ audio }) => audio)).toEqual([
      'http://127.0.0.1/calm.wav',
      'http://127.0.0.1/calm.wav',
      'http://127.0.0.1/annoyed.wav',
      'http://127.0.0.1/surprised.wav',
    ])
    expect(played.map(({ volumes }) => volumes)).toEqual([[0.1], [0.1], [0.5], [0.9]])
    expect(interruptions).toBe(1)
    expect(handle?.element.dataset.interruption).toBe('observed')
    expect(handle?.element.dataset.complete).toBe('true')
    expect(handle?.element.dataset.currentBase).toBe('calm')
    handle?.dispose()
    handle?.dispose()
    expect(document.querySelector('.live2d-performance-review')).toBeNull()
    vi.useRealTimers()
  })

  it('keeps only the three visually distinct expression groups', () => {
    expect(PERFORMANCE_BASES).toEqual(['calm', 'annoyed', 'surprised'])
    expect(PERFORMANCE_ACCENTS).toEqual([])
    expect(PERFORMANCE_REVIEW_PLANS).toHaveLength(3)
  })
})
