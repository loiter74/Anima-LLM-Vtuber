// @vitest-environment node

import { describe, expect, it } from 'vitest'
import { parseReviewOptions } from '../scripts/review/options'

describe('review CLI options', () => {
  it('defaults to automatic OBS-backed live review', () => {
    expect(parseReviewOptions([], {})).toEqual({
      featureId: 'live',
      baseUrl: 'http://127.0.0.1:3000',
      interactive: false,
      headed: true,
      requireObs: true,
      obsUrl: 'ws://127.0.0.1:4455',
      obsSceneName: 'Animetta Review',
      obsSourceName: 'Animetta Live Browser',
      verdict: null,
    })
  })

  it('makes interactive review headed and supports explicit browser-only mode', () => {
    expect(parseReviewOptions(['--interactive', '--no-obs'], {})).toEqual(
      expect.objectContaining({
        interactive: true,
        headed: true,
        requireObs: false,
      }),
    )
  })

  it('allows automation hosts to opt into headless mode explicitly', () => {
    expect(parseReviewOptions(['--headless'], {})).toEqual(
      expect.objectContaining({
        interactive: false,
        headed: false,
      }),
    )
  })

  it('accepts a pre-approved verdict only for interactive review', () => {
    expect(parseReviewOptions(['--interactive', '--verdict', 'pass'], {})).toEqual(
      expect.objectContaining({
        interactive: true,
        verdict: 'pass',
      }),
    )
    expect(() => parseReviewOptions(['--verdict', 'pass'], {})).toThrow(
      /--verdict requires --interactive/,
    )
  })

  it('allows OBS connection and source names through environment or CLI overrides', () => {
    expect(
      parseReviewOptions(['--obs-source', 'CLI Source'], {
        OBS_WEBSOCKET_URL: 'ws://127.0.0.1:4466',
        OBS_SCENE_NAME: 'Environment Scene',
        OBS_SOURCE_NAME: 'Environment Source',
      }),
    ).toEqual(
      expect.objectContaining({
        obsUrl: 'ws://127.0.0.1:4466',
        obsSceneName: 'Environment Scene',
        obsSourceName: 'CLI Source',
      }),
    )
  })

  it('rejects unknown flags and missing values', () => {
    expect(() => parseReviewOptions(['--unknown'], {})).toThrow(/Unknown option/)
    expect(() => parseReviewOptions(['--feature'], {})).toThrow(/requires a value/)
  })
})
