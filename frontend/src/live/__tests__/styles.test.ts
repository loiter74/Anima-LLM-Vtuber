import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const liveStyles = readFileSync(resolve(process.cwd(), 'src/live/styles.css'), 'utf8')

describe('standalone live panel styles', () => {
  it('keeps the desktop panel inside the right half of the review viewport', () => {
    expect(liveStyles).toMatch(/\.danmaku-panel\s*\{[^}]*width:\s*min\(500px,/s)
  })

  it('caps the danmaku list above the Live2D model', () => {
    expect(liveStyles).toMatch(/\.danmaku-list\s*\{[^}]*max-height:\s*min\(460px,\s*28vh\)/s)
  })

  it('composites the Live2D model in front of the danmaku panel', () => {
    expect(liveStyles).toMatch(/\.live2d-stage\s*\{[^}]*z-index:\s*1/s)
    expect(liveStyles).toMatch(/\.danmaku-panel\s*\{[^}]*z-index:\s*0/s)
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

  it('keeps the public subtitle above the model using theme tokens', () => {
    expect(liveStyles).toMatch(/\.subtitle-overlay\s*\{[^}]*z-index:\s*20/s)
    expect(liveStyles).toMatch(/\.subtitle-overlay\s*\{[^}]*var\(--c-panel\)/s)
    expect(liveStyles).toMatch(
      /\.subtitle-overlay p\s*\{[^}]*font-size:\s*clamp\(30px,\s*3\.4vw,\s*40px\)/s,
    )
    expect(liveStyles).toMatch(/\.subtitle-overlay p\s*\{[^}]*font-weight:\s*500/s)
  })

  it('keeps mobile chrome inside the dynamic viewport without covering the panel heading', () => {
    expect(liveStyles).toMatch(/\.live-shell\s*\{[^}]*height:\s*100dvh/s)
    expect(liveStyles).toMatch(
      /@media \(max-width: 600px\)[\s\S]*\.danmaku-panel\s*\{[^}]*top:\s*62px/s,
    )
    expect(liveStyles).toMatch(
      /@media \(max-width: 600px\)[\s\S]*\.status-rail\s*\{[^}]*right:\s*16px[^}]*flex-wrap:\s*nowrap/s,
    )
    expect(liveStyles).toMatch(
      /@media \(max-width: 600px\)[\s\S]*\.status-pill\s*\{[^}]*font-size:\s*12px/s,
    )
  })
})
