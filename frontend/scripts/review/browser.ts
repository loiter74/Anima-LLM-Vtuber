import type { Browser, Locator, Page } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { ReviewScene } from '../../src/review/contracts'
import { comparePngRegion, type ImageRegion } from './image-compare'
import type { ReviewPluginArtifacts } from './registry'

export interface AssertionRecord {
  name: string
  passed: boolean
  detail?: string
}

export interface PageAssertionResult {
  assertions: AssertionRecord[]
  stableLocator: Locator
  stableRegion: ImageRegion
}

export interface ReviewPageAdapter<Action> {
  viewport?: Readonly<{ width: number; height: number }>
  forbiddenRequestPatterns?: readonly RegExp[]
  stableMismatchThreshold?: number
  buildUrl(input: {
    baseUrl: string
    runId: string
    sceneId: string
    attempt: number
    pageParams?: Readonly<Record<string, string>>
  }): string
  assertPage(page: Page, scene: ReviewScene<string, Action>): Promise<PageAssertionResult>
}

export interface PreviewAdapter {
  updateSource(reviewUrl: string): Promise<void>
  capture(): Promise<Buffer>
}

export interface BrowserAttemptResult {
  reviewUrl: string
  technicalPassed: boolean
  assertions: AssertionRecord[]
  consoleErrors: string[]
  pageErrors: string[]
  failedRequests: Array<{ url: string; error: string }>
  chromeScreenshot: string
  chromeStableCrop: string
  obsScreenshot: string | null
  playwrightTrace: string
  obsMismatchRatio: number | null
  startedAt: string
  finishedAt: string
  observations?: readonly StructuredObservation[]
  pluginArtifacts?: ReviewPluginArtifacts
}

export interface StructuredObservation {
  name: string
  value: string | number | boolean
  unit?: string
}

interface PreviewSyncOptions {
  maxAttempts: number
  intervalMs: number
}

export function buildReviewBrowserArgs(options: {
  requireObs: boolean
  enableObsAudioMonitoring: boolean
}): string[] {
  const args = ['--autoplay-policy=no-user-gesture-required']
  if (options.requireObs && options.enableObsAudioMonitoring) args.push('--mute-audio')
  return args
}

export async function assertHardwareWebGl(browser: Browser): Promise<string> {
  const context = await browser.newContext()
  try {
    const page = await context.newPage()
    const renderer = await page.evaluate(() => {
      const canvas = document.createElement('canvas')
      const gl = canvas.getContext('webgl2') ?? canvas.getContext('webgl')
      if (!gl) return 'unavailable'
      const extension = gl.getExtension('WEBGL_debug_renderer_info')
      return extension
        ? String(gl.getParameter(extension.UNMASKED_RENDERER_WEBGL))
        : String(gl.getParameter(gl.RENDERER))
    })
    if (
      /swiftshader|software|llvmpipe|softpipe|basic render driver|\bwarp\b|unavailable/i.test(
        renderer,
      )
    ) {
      throw new Error(`Live2D performance review requires hardware WebGL; renderer=${renderer}`)
    }
    return renderer
  } finally {
    await context.close()
  }
}

function waitFor(delayMs: number): Promise<void> {
  return delayMs > 0
    ? new Promise((resolve) => {
        setTimeout(resolve, delayMs)
      })
    : Promise.resolve()
}

export async function captureBrowserAttempt<Action>(_options: {
  browser: Browser
  runDir: string
  runId: string
  scene: ReviewScene<string, Action>
  attempt: number
  baseUrl: string
  pageAdapter: ReviewPageAdapter<Action>
  pageParams?: Readonly<Record<string, string>>
  initialAssertions?: readonly AssertionRecord[]
  preview?: PreviewAdapter
  previewSync?: Partial<PreviewSyncOptions>
}): Promise<BrowserAttemptResult> {
  const evidenceDir = join(_options.runDir, 'evidence')
  await mkdir(evidenceDir, { recursive: true })
  const stem = `${_options.scene.id}-${String(_options.attempt).padStart(3, '0')}`
  const chromeScreenshot = join(evidenceDir, `${stem}-chrome.png`)
  const chromeStableCrop = join(evidenceDir, `${stem}-chrome-stable.png`)
  const obsScreenshot = _options.preview ? join(evidenceDir, `${stem}-obs.png`) : null
  const playwrightTrace = join(evidenceDir, `${stem}-trace.zip`)
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  const failedRequests: Array<{ url: string; error: string }> = []
  const requestedUrls: string[] = []
  const assertions: AssertionRecord[] = [...(_options.initialAssertions ?? [])]
  const startedAt = new Date().toISOString()
  const reviewUrl = _options.pageAdapter.buildUrl({
    baseUrl: _options.baseUrl,
    runId: _options.runId,
    sceneId: _options.scene.id,
    attempt: _options.attempt,
    pageParams: _options.pageParams,
  })
  const context = await _options.browser.newContext({
    viewport: _options.pageAdapter.viewport ?? { width: 1080, height: 1920 },
  })
  let page: Page | null = null
  let traceStarted = false
  let screenshotCaptured = false
  let obsMismatchRatio: number | null = null

  try {
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
    traceStarted = true
    page = await context.newPage()
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('request', (request) => requestedUrls.push(request.url()))
    page.on('requestfailed', (request) => {
      failedRequests.push({
        url: request.url(),
        error: request.failure()?.errorText ?? 'unknown request failure',
      })
    })
    page.on('response', (response) => {
      if (response.status() >= 400) {
        failedRequests.push({ url: response.url(), error: `HTTP ${response.status()}` })
      }
    })

    await _options.preview?.updateSource(reviewUrl)
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' })
    const pageResult = await _options.pageAdapter.assertPage(page, _options.scene)
    assertions.push(...pageResult.assertions)
    const stableCrop = await pageResult.stableLocator.screenshot()
    await writeFile(chromeStableCrop, stableCrop)

    if (_options.preview && obsScreenshot) {
      const syncOptions: PreviewSyncOptions = {
        maxAttempts: _options.previewSync?.maxAttempts ?? 12,
        intervalMs: _options.previewSync?.intervalMs ?? 250,
      }
      let obsCapture = await _options.preview.capture()
      let comparison = comparePngRegion(
        Buffer.from(stableCrop),
        obsCapture,
        pageResult.stableRegion,
        _options.pageAdapter.stableMismatchThreshold,
      )
      for (
        let syncAttempt = 1;
        !comparison.passed && syncAttempt < syncOptions.maxAttempts;
        syncAttempt += 1
      ) {
        await waitFor(syncOptions.intervalMs)
        obsCapture = await _options.preview.capture()
        comparison = comparePngRegion(
          Buffer.from(stableCrop),
          obsCapture,
          pageResult.stableRegion,
          _options.pageAdapter.stableMismatchThreshold,
        )
      }
      await writeFile(obsScreenshot, obsCapture)
      obsMismatchRatio = comparison.mismatchRatio
      assertions.push({
        name: 'chrome-obs-stable-region',
        passed: comparison.passed,
        detail: `mismatchRatio=${comparison.mismatchRatio}`,
      })
    }

    await page.screenshot({ path: chromeScreenshot, fullPage: false })
    screenshotCaptured = true
    for (const pattern of _options.pageAdapter.forbiddenRequestPatterns ?? []) {
      const forbiddenUrl = requestedUrls.find((url) => pattern.test(url))
      assertions.push({
        name: `forbidden-request:${pattern.source}`,
        passed: forbiddenUrl === undefined,
        detail: forbiddenUrl,
      })
    }
  } catch (error) {
    assertions.push({
      name: 'browser-attempt',
      passed: false,
      detail: error instanceof Error ? error.message : String(error),
    })
  } finally {
    if (page && !screenshotCaptured) {
      await page.screenshot({ path: chromeScreenshot, fullPage: false }).catch(() => {})
    }
    if (traceStarted) await context.tracing.stop({ path: playwrightTrace }).catch(() => {})
    await context.close()
  }

  const technicalPassed =
    assertions.length > 0 &&
    assertions.every(({ passed }) => passed) &&
    consoleErrors.length === 0 &&
    pageErrors.length === 0 &&
    failedRequests.length === 0
  return {
    reviewUrl,
    technicalPassed,
    assertions,
    consoleErrors,
    pageErrors,
    failedRequests,
    chromeScreenshot,
    chromeStableCrop,
    obsScreenshot,
    playwrightTrace,
    obsMismatchRatio,
    startedAt,
    finishedAt: new Date().toISOString(),
  }
}
