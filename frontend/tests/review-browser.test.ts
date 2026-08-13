// @vitest-environment node

import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PNG } from 'pngjs'
import { describe, expect, it, vi } from 'vitest'
import {
  assertHardwareWebGl,
  buildReviewBrowserArgs,
  captureBrowserAttempt,
  type ReviewPageAdapter,
} from '../scripts/review/browser'

function png(width = 2, height = 2): Buffer {
  const image = new PNG({ width, height })
  image.data.fill(255)
  return PNG.sync.write(image)
}

function darkPng(width = 2, height = 2): Buffer {
  const image = new PNG({ width, height })
  image.data.fill(0)
  return PNG.sync.write(image)
}

function harness() {
  const calls: string[] = []
  const listeners = new Map<string, (value: unknown) => void>()
  const locator = {
    screenshot: vi.fn(async () => {
      calls.push('stableScreenshot')
      return png()
    }),
  }
  const page = {
    on: vi.fn((event: string, callback: (value: unknown) => void) => {
      listeners.set(event, callback)
    }),
    goto: vi.fn(async () => {
      calls.push('goto')
    }),
    screenshot: vi.fn(async ({ path }: { path: string }) => {
      calls.push(`pageScreenshot:${path}`)
      return png(1080, 1920)
    }),
  }
  const context = {
    tracing: {
      start: vi.fn(async () => {
        calls.push('traceStart')
      }),
      stop: vi.fn(async () => {
        calls.push('traceStop')
      }),
    },
    newPage: vi.fn(async () => page),
    close: vi.fn(async () => {
      calls.push('contextClose')
    }),
  }
  const browser = {
    newContext: vi.fn(async () => context),
  }
  const pageAdapter: ReviewPageAdapter<never> = {
    buildUrl: () => 'http://127.0.0.1:3000/live.html?review=1&scene=empty',
    assertPage: vi.fn(async () => ({
      assertions: [{ name: 'viewport', passed: true }],
      stableLocator: locator as never,
      stableRegion: { x: 0, y: 0, width: 2, height: 2 },
    })),
  }
  return { browser, calls, listeners, locator, pageAdapter }
}

describe('generic Playwright attempt capture', () => {
  it.each([
    ['ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device))', false],
    ['ANGLE (Microsoft, Microsoft Basic Render Driver, D3D11)', false],
    ['ANGLE (NVIDIA, NVIDIA GeForce RTX 5090 D v2)', true],
  ])('validates the WebGL renderer %s and closes its context', async (renderer, supported) => {
    const close = vi.fn().mockResolvedValue(undefined)
    const browser = {
      newContext: vi.fn(async () => ({
        newPage: vi.fn(async () => ({
          evaluate: vi.fn(async () => renderer),
        })),
        close,
      })),
    }

    const result = assertHardwareWebGl(browser as never)
    if (supported) await expect(result).resolves.toBe(renderer)
    else await expect(result).rejects.toThrow(/hardware WebGL/)
    expect(close).toHaveBeenCalledOnce()
  })

  it('mutes the Playwright copy when OBS owns monitored review audio', () => {
    expect(
      buildReviewBrowserArgs({
        requireObs: true,
        enableObsAudioMonitoring: true,
      }),
    ).toEqual(['--autoplay-policy=no-user-gesture-required', '--mute-audio'])
    expect(
      buildReviewBrowserArgs({
        requireObs: false,
        enableObsAudioMonitoring: true,
      }),
    ).not.toContain('--mute-audio')
    expect(
      buildReviewBrowserArgs({
        requireObs: true,
        enableObsAudioMonitoring: false,
      }),
    ).not.toContain('--mute-audio')
  })

  it('uses a fresh vertical context and stops trace only after final Chrome and OBS capture', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-browser-attempt-'))
    const test = harness()
    const preview = {
      updateSource: vi.fn(async () => {
        test.calls.push('previewUpdate')
      }),
      capture: vi.fn(async () => {
        test.calls.push('previewCapture')
        return png(1080, 1920)
      }),
    }

    const result = await captureBrowserAttempt({
      browser: test.browser as never,
      runDir: root,
      runId: 'run-1',
      scene: {
        id: 'empty',
        title: 'empty',
        observe: 'empty',
        readyTexts: [],
        timeline: [],
      },
      attempt: 1,
      baseUrl: 'http://127.0.0.1:3000',
      pageAdapter: test.pageAdapter,
      preview,
    })

    expect(test.browser.newContext).toHaveBeenCalledWith({
      viewport: { width: 1080, height: 1920 },
    })
    expect(test.calls.indexOf('previewCapture')).toBeLessThan(test.calls.indexOf('traceStop'))
    expect(test.calls.findIndex((entry) => entry.startsWith('pageScreenshot:'))).toBeLessThan(
      test.calls.indexOf('traceStop'),
    )
    expect(test.calls.at(-1)).toBe('contextClose')
    expect(result.technicalPassed).toBe(true)
    expect(result.obsMismatchRatio).toBe(0)
  })

  it('uses a page adapter viewport for horizontal review features', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-browser-horizontal-'))
    const test = harness()
    test.pageAdapter.viewport = { width: 1920, height: 1080 }

    await captureBrowserAttempt({
      browser: test.browser as never,
      runDir: root,
      runId: 'run-horizontal',
      scene: {
        id: 'horizontal',
        title: 'horizontal',
        observe: 'horizontal',
        readyTexts: [],
        timeline: [],
      },
      attempt: 1,
      baseUrl: 'http://127.0.0.1:3000',
      pageAdapter: test.pageAdapter,
    })

    expect(test.browser.newContext).toHaveBeenCalledWith({
      viewport: { width: 1920, height: 1080 },
    })
  })

  it('records errors that arrive while OBS evidence is being captured', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-browser-late-error-'))
    const test = harness()
    const preview = {
      updateSource: vi.fn().mockResolvedValue(undefined),
      capture: vi.fn(async () => {
        test.listeners.get('console')?.({
          type: () => 'error',
          text: () => 'late console failure',
        })
        return png(1080, 1920)
      }),
    }

    const result = await captureBrowserAttempt({
      browser: test.browser as never,
      runDir: root,
      runId: 'run-2',
      scene: {
        id: 'empty',
        title: 'empty',
        observe: 'empty',
        readyTexts: [],
        timeline: [],
      },
      attempt: 1,
      baseUrl: 'http://127.0.0.1:3000',
      pageAdapter: test.pageAdapter,
      preview,
    })

    expect(result.technicalPassed).toBe(false)
    expect(result.consoleErrors).toEqual(['late console failure'])
    expect(test.calls.indexOf('previewCapture')).toBeLessThan(test.calls.indexOf('traceStop'))
  })

  it('polls bounded OBS captures until the stable region is synchronized', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-browser-obs-sync-'))
    const test = harness()
    const preview = {
      updateSource: vi.fn().mockResolvedValue(undefined),
      capture: vi
        .fn<() => Promise<Buffer>>()
        .mockResolvedValueOnce(darkPng(1080, 1920))
        .mockResolvedValueOnce(png(1080, 1920)),
    }

    const result = await captureBrowserAttempt({
      browser: test.browser as never,
      runDir: root,
      runId: 'run-3',
      scene: {
        id: 'empty',
        title: 'empty',
        observe: 'empty',
        readyTexts: [],
        timeline: [],
      },
      attempt: 1,
      baseUrl: 'http://127.0.0.1:3000',
      pageAdapter: test.pageAdapter,
      preview,
      previewSync: { maxAttempts: 2, intervalMs: 0 },
    })

    expect(preview.capture).toHaveBeenCalledTimes(2)
    expect(result.technicalPassed).toBe(true)
    expect(result.obsMismatchRatio).toBe(0)
  })
})
