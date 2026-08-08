// @vitest-environment node

import { describe, expect, it, vi } from 'vitest'

import { getReviewPlugin, REVIEW_FEATURE_IDS } from '../scripts/review/registry'
import { MinecraftObsCompositeAdapter } from '../scripts/review/minecraft-obs'
import { resolveMinecraftStableIndicator } from '../scripts/review/plugins/minecraft-gameplay'

describe('minecraft gameplay review plugin', () => {
  it('registers the independent full-OBS gameplay scenes', () => {
    expect(REVIEW_FEATURE_IDS).toContain('minecraft-gameplay')
    const plugin = getReviewPlugin('minecraft-gameplay')

    expect(plugin.definition.route).toBe('/minecraft-gameplay.html')
    expect(plugin.definition.viewport).toEqual({ width: 1920, height: 1080 })
    expect(plugin.definition.scenes.map(({ id }) => id)).toEqual([
      'survival-iron',
      'adaptive-mission',
    ])
    expect(plugin.capabilities).toEqual({
      requireObs: true,
      requireInteractive: true,
      requireHostTts: true,
    })
  })

  it('creates the additive composite adapter without changing the default OBS adapter', () => {
    const plugin = getReviewPlugin('minecraft-gameplay')
    const client = {
      connect: vi.fn(),
      call: vi.fn(),
      disconnect: vi.fn(),
    }

    const adapter = plugin.createObsAdapter?.(client, {
      url: 'ws://127.0.0.1:4455',
      sceneName: 'Minecraft Review',
      sourceName: 'Minecraft Overlay',
      width: 1920,
      height: 1080,
    })

    expect(adapter).toBeInstanceOf(MinecraftObsCompositeAdapter)
  })

  it('uses the opaque status dot as the Chrome-to-OBS synchronization anchor', () => {
    const indicator = { boundingBox: vi.fn() }
    const page = {
      locator: vi.fn().mockReturnValue(indicator),
    }

    expect(resolveMinecraftStableIndicator(page as never)).toBe(indicator)
    expect(page.locator).toHaveBeenCalledWith('.possession-status .status-dot')
  })

  it('allows bounded antialiasing variance for the tiny status-dot anchor', () => {
    expect(getReviewPlugin('minecraft-gameplay').pageAdapter.stableMismatchThreshold).toBe(0.25)
  })
})
