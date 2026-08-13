// @vitest-environment node

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  getReviewPlugin,
  REVIEW_FEATURE_IDS,
  validateReviewCapabilities,
} from '../scripts/review/registry'

describe('TTS failover review plugin', () => {
  const pluginSource = readFileSync(
    resolve(process.cwd(), 'scripts/review/plugins/tts-failover.ts'),
    'utf8',
  )

  it('registers an independent fixed billing-to-local feature', () => {
    const plugin = getReviewPlugin('tts-failover')

    expect(REVIEW_FEATURE_IDS).toContain('tts-failover')
    expect(plugin.definition.id).toBe('tts-failover')
    expect(plugin.definition.route).toBe('/live.html')
    expect(plugin.definition.contractVersion).toBe(2)
    expect(plugin.definition.scenes.map(({ id }) => id)).toEqual(['billing-to-local'])
    expect(plugin.definition.scenes[0]?.readyTexts).toEqual(['云端语音暂不可用', '本地语音已接管'])

    const reviewUrl = plugin.pageAdapter.buildUrl({
      baseUrl: 'http://127.0.0.1:3000',
      runId: 'run-1',
      sceneId: 'billing-to-local',
      attempt: 1,
      pageParams: {
        audio: 'http://127.0.0.1:8768/artifacts/a.wav',
        backend: 'fallback',
        mouthTimeline: '[0.1,0.5]',
      },
    })
    const parsed = new URL(reviewUrl)
    expect(parsed.pathname).toBe('/live.html')
    expect(Object.fromEntries(parsed.searchParams)).toMatchObject({
      review: '1',
      scene: 'empty',
      ttsFailover: '1',
      audio: 'http://127.0.0.1:8768/artifacts/a.wav',
      backend: 'fallback',
      mouthTimeline: '[0.1,0.5]',
    })
  })

  it('requires OBS, interactive review, and the host TTS credential', () => {
    const plugin = getReviewPlugin('tts-failover')

    expect(() =>
      validateReviewCapabilities(plugin, {
        requireObs: false,
        interactive: true,
        headed: true,
        hostTtsAvailable: true,
      }),
    ).toThrow(/OBS/)
    expect(() =>
      validateReviewCapabilities(plugin, {
        requireObs: true,
        interactive: false,
        headed: true,
        hostTtsAvailable: true,
      }),
    ).toThrow(/interactive/)
    expect(() =>
      validateReviewCapabilities(plugin, {
        requireObs: true,
        interactive: true,
        headed: true,
        hostTtsAvailable: false,
      }),
    ).toThrow(/host TTS/)
    expect(() =>
      validateReviewCapabilities(plugin, {
        requireObs: true,
        interactive: true,
        headed: true,
        hostTtsAvailable: true,
      }),
    ).not.toThrow()
  })

  it('asserts that the collapsed notification occupies the measured top-bar gap', () => {
    expect(pluginSource).toContain("'notification-collapsed'")
    expect(pluginSource).toContain("'notification-in-adaptive-top-gap'")
    expect(pluginSource).toContain('statusBox')
    expect(pluginSource).toContain('safeGapLeft')
    expect(pluginSource).toContain('safeGapRight')
    expect(pluginSource).toContain('boxesIntersect')
    expect(pluginSource).not.toContain("'notification-in-central-safe-area'")
  })
})
