import { describe, expect, it } from 'vitest'

import { MINECRAFT_GAMEPLAY_LAYOUT, resolveMinecraftGameplayMode, toCssVariables } from './layout'

describe('minecraft gameplay broadcast layout', () => {
  it('uses a fixed 1920x1080 canvas and a 16:9 television aperture', () => {
    const { canvas, television, aperture } = MINECRAFT_GAMEPLAY_LAYOUT

    expect(canvas).toEqual({ width: 1920, height: 1080 })
    expect(television.x + television.width / 2).toBe(canvas.width / 2)
    expect(aperture.x + aperture.width / 2).toBe(canvas.width / 2)
    expect(aperture.width / aperture.height).toBeCloseTo(16 / 9, 3)
    expect(aperture.width / canvas.width).toBeGreaterThan(0.75)
    expect(television.x).toBeLessThan(aperture.x)
    expect(television.y).toBeLessThan(aperture.y)
    expect(television.x + television.width).toBeGreaterThan(aperture.x + aperture.width)
    expect(television.y + television.height).toBeGreaterThan(aperture.y + aperture.height)
  })

  it('keeps danmaku inside the screen and the avatar outside its primary viewing area', () => {
    const { canvas, aperture, danmaku, avatar, subtitle } = MINECRAFT_GAMEPLAY_LAYOUT

    expect(danmaku.x).toBeGreaterThan(aperture.x)
    expect(danmaku.y).toBeGreaterThan(aperture.y)
    expect(danmaku.x + danmaku.width).toBeLessThan(aperture.x + aperture.width)
    expect(danmaku.y + danmaku.height).toBeLessThan(aperture.y + aperture.height)
    expect(avatar.x + avatar.width).toBeGreaterThan(aperture.x + aperture.width)
    expect(avatar.x + avatar.width / 2).toBeGreaterThan(aperture.x + aperture.width - 40)
    expect(avatar.y + avatar.height).toBeGreaterThan(aperture.y + aperture.height)
    expect(subtitle.y).toBeGreaterThanOrEqual(aperture.y + aperture.height)
    expect(subtitle.x + subtitle.width / 2).toBe(canvas.width / 2)
  })

  it('uses preview mode by default and overlay only when explicitly requested', () => {
    expect(resolveMinecraftGameplayMode(new URLSearchParams())).toBe('preview')
    expect(resolveMinecraftGameplayMode(new URLSearchParams('preview=1'))).toBe('preview')
    expect(resolveMinecraftGameplayMode(new URLSearchParams('overlay=1'))).toBe('overlay')
    expect(resolveMinecraftGameplayMode(new URLSearchParams('preview=1&overlay=1'))).toBe('overlay')
  })

  it('exports the geometry as deterministic CSS variables', () => {
    expect(toCssVariables(MINECRAFT_GAMEPLAY_LAYOUT)).toMatchObject({
      '--broadcast-width': '1920px',
      '--broadcast-height': '1080px',
      '--screen-width': '1488px',
      '--screen-height': '837px',
    })
  })
})
