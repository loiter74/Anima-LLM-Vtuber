import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const liveStyles = readFileSync(resolve(process.cwd(), 'src/live/styles.css'), 'utf8')

describe('standalone live panel styles', () => {
  it('caps the danmaku list above the Live2D model', () => {
    expect(liveStyles).toMatch(/\.danmaku-list\s*\{[^}]*max-height:\s*min\(290px,\s*24vh\)/s)
  })

  it('hides the danmaku scrollbar while preserving scrolling', () => {
    expect(liveStyles).toMatch(
      /\.danmaku-list\s*\{[^}]*overflow:\s*auto[^}]*scrollbar-width:\s*none/s,
    )
    expect(liveStyles).toMatch(/\.danmaku-list::-(?:webkit-)?scrollbar\s*\{[^}]*display:\s*none/s)
  })

  it('uses existing theme tokens for gift and super-chat labels', () => {
    expect(liveStyles).toMatch(/\.danmaku-kind--gift\s*\{[^}]*var\(--c-success\)/s)
    expect(liveStyles).toMatch(/\.danmaku-kind--super-chat\s*\{[^}]*var\(--c-accent\)/s)
  })
})
