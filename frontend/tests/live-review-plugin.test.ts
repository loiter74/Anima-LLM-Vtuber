// @vitest-environment node

import { describe, expect, it } from 'vitest'
import { createSemanticFingerprint } from '../scripts/review/evidence'
import { liveReviewNodePlugin } from '../scripts/review/plugins/live'

describe('livestream review plugin', () => {
  it('exposes the frozen scene order from the single browser catalog', () => {
    expect(liveReviewNodePlugin.definition.scenes.map(({ id }) => id)).toEqual([
      'empty',
      'baseline',
      'text-boundaries',
      'sparse',
      'burst',
      'special',
      'recovery',
      'overall',
    ])
    expect(
      liveReviewNodePlugin.definition.scenes.find(({ id }) => id === 'special')?.readyTexts,
    ).toContain('送出「摸鱼许可证」×1')
  })

  it('builds the stable local URL and forbids production Socket.IO requests', () => {
    expect(
      liveReviewNodePlugin.pageAdapter.buildUrl({
        baseUrl: 'http://127.0.0.1:3000',
        runId: 'run-1',
        sceneId: 'sparse',
        attempt: 2,
      }),
    ).toBe('http://127.0.0.1:3000/live.html?review=1&scene=sparse&attempt=run-1-2')
    expect(
      liveReviewNodePlugin.pageAdapter.forbiddenRequestPatterns?.some((pattern) =>
        pattern.test('http://127.0.0.1:3000/socket.io/?transport=websocket'),
      ),
    ).toBe(true)
  })

  it('fingerprints semantic catalog data and explicit contract version', () => {
    const definition = liveReviewNodePlugin.definition
    const fingerprint = createSemanticFingerprint({
      featureId: definition.id,
      contractVersion: definition.contractVersion,
      route: definition.route,
      viewport: definition.viewport,
      scenes: definition.scenes,
      evidenceSchemaVersion: 2,
      profile: 'full',
    })

    expect(fingerprint).toMatch(/^[a-f0-9]{64}$/)
  })
})
