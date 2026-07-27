import { describe, expect, it } from 'vitest'
import {
  getReviewPlugin,
  REVIEW_FEATURE_IDS,
  validateReviewCapabilities,
} from '../scripts/review/registry'

describe('live2d-performance review plugin', () => {
  it('is isolated from the live catalog and declares required capabilities', () => {
    const plugin = getReviewPlugin('live2d-performance')

    expect(REVIEW_FEATURE_IDS).toContain('live2d-performance')
    expect(plugin.definition.id).toBe('live2d-performance')
    expect(plugin.definition.scenes.map(({ id }) => id)).toEqual(['semantic-catalog'])
    expect(() =>
      validateReviewCapabilities(plugin, {
        requireObs: true,
        interactive: true,
        hostTtsAvailable: true,
      }),
    ).not.toThrow()
  })
})
