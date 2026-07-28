import { describe, expect, it } from 'vitest'
import {
  DEFAULT_LIVE2D_PERFORMANCE_PLAN,
  LIVE2D_PERFORMANCE_BASES,
  normalizeLive2DPerformancePlan,
} from './live2dPerformanceContract'

describe('Live2D performance contract', () => {
  it('publishes only the three accepted semantic bases', () => {
    expect(LIVE2D_PERFORMANCE_BASES).toEqual(['calm', 'annoyed', 'surprised'])
    expect(DEFAULT_LIVE2D_PERFORMANCE_PLAN).toEqual({
      version: 1,
      base: 'calm',
      intensity: 'subtle',
      accent: 'none',
      source: 'fallback',
    })
  })

  it.each([
    ['cheerful', 'none', 'calm'],
    ['concerned', 'none', 'annoyed'],
    ['thinking', 'skeptical', 'calm'],
    ['smug', 'sigh', 'calm'],
  ])('normalizes deprecated %s/%s inputs at the ingress boundary', (base, accent, expected) => {
    expect(
      normalizeLive2DPerformancePlan({
        version: 1,
        base,
        intensity: 'medium',
        accent,
        source: 'llm',
      }),
    ).toEqual({
      plan: {
        version: 1,
        base: expected,
        intensity: 'medium',
        accent: 'none',
        source: 'legacy',
      },
      fallback: 'none',
    })
  })

  it('rejects an unbounded payload without leaking its values', () => {
    expect(
      normalizeLive2DPerformancePlan({
        version: 1,
        base: 'furious',
        intensity: 'extreme',
        accent: 'dance',
        source: 'llm',
      }),
    ).toEqual({
      plan: DEFAULT_LIVE2D_PERFORMANCE_PLAN,
      fallback: 'invalid_payload',
    })
  })
})
