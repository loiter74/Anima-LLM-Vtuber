import { describe, expect, it } from 'vitest'

import liveMarkup from '../../../live.html?raw'
import mainSource from '../main.ts?raw'

describe('live review entry styles', () => {
  it('loads the UnoCSS entry before live-specific styles', () => {
    expect(mainSource).toMatch(
      /import ['"]virtual:uno\.css['"][\s\S]*import ['"]\.\/styles\.css['"]/,
    )
  })

  it('loads the review-only TTS takeover notification on the live surface', () => {
    expect(mainSource).toContain("from '@/tts-failover/main'")
  })

  it('does not render a danmaku collapse affordance', () => {
    expect(liveMarkup).not.toContain('id="togglePanel"')
    expect(liveMarkup).not.toContain('aria-label="折叠弹幕"')
  })
})
