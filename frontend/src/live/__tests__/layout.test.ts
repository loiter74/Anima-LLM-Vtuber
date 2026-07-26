import { describe, expect, it } from 'vitest'

import { applyLiveReviewLayout, computeLive2DLayout } from '../layout'

describe('livestream review layout', () => {
  it('renders the Live2D model at twice the fitted scale', () => {
    expect(
      computeLive2DLayout({
        screenWidth: 1080,
        screenHeight: 1920,
        baseWidth: 1000,
        baseHeight: 1000,
      }),
    ).toEqual({
      scale: 1.9008,
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
