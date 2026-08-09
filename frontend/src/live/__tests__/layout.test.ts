import { describe, expect, it } from 'vitest'

import { applyLiveReviewLayout, computeLive2DLayout } from '../layout'

describe('livestream review layout', () => {
  it('keeps the Live2D model compact enough for the danmaku panel', () => {
    expect(
      computeLive2DLayout({
        screenWidth: 1080,
        screenHeight: 1920,
        baseWidth: 1000,
        baseHeight: 1000,
      }),
    ).toEqual({
      scale: 1.4256,
      x: 540,
      y: 1536,
    })
  })

  it('anchors the danmaku panel near the upper-right corner', () => {
    applyLiveReviewLayout(document.documentElement)

    expect(document.documentElement.style.getPropertyValue('--live-danmaku-panel-top')).toBe('28px')
    expect(document.documentElement.style.getPropertyValue('--live-danmaku-panel-bottom')).toBe('')
  })
})
