import { expect, type Page } from 'playwright/test'
import {
  LIVE2D_PERFORMANCE_REVIEW_DEFINITION,
  PERFORMANCE_ACCENTS,
  PERFORMANCE_BASES,
} from '../../../src/live2d-performance/catalog'
import type { AssertionRecord, PageAssertionResult, ReviewPageAdapter } from '../browser'
import { recordAssertion as check } from '../assertions'
import { TtsHarnessLease } from '../tts-harness-lease'

async function assertPage(page: Page): Promise<PageAssertionResult> {
  const assertions: AssertionRecord[] = []
  const panel = page.getByLabel('Live2D 语义表演评审')
  await check(assertions, 'live2d-stage-visible', () =>
    expect(page.getByLabel('Live2D 舞台')).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'performance-panel-visible', () =>
    expect(panel).toBeVisible({ timeout: 20_000 }),
  )
  for (const semantic of [...PERFORMANCE_BASES, ...PERFORMANCE_ACCENTS]) {
    await check(assertions, `catalog:${semantic}`, () => expect(panel).toContainText(semantic))
  }
  await check(assertions, 'semantic-sequence-complete', () =>
    expect(panel).toHaveAttribute('data-complete', 'true', { timeout: 150_000 }),
  )
  await check(assertions, 'lip-sync-observed', () =>
    expect(panel).toHaveAttribute('data-lip-sync', 'observed'),
  )
  await check(assertions, 'interruption-returned-to-calm', () =>
    expect(panel).toHaveAttribute('data-interruption', 'observed'),
  )
  await check(assertions, 'settled-to-calm', async () => {
    await expect(panel).toHaveAttribute('data-current-base', 'calm')
    await expect(panel).toHaveAttribute('data-current-accent', 'none')
  })
  await check(assertions, 'audio-not-blocked', () =>
    expect(page.locator('#reviewAudio')).not.toHaveAttribute('data-complete', 'blocked'),
  )
  const box = await page.getByLabel('Live2D 舞台').boundingBox()
  return {
    assertions,
    stableLocator: page.getByLabel('Live2D 舞台'),
    stableRegion: {
      x: box?.x ?? 0,
      y: box?.y ?? 0,
      width: box?.width ?? 1,
      height: box?.height ?? 1,
    },
  }
}

const pageAdapter: ReviewPageAdapter<never> = {
  buildUrl({ baseUrl, pageParams }) {
    const url = new URL(LIVE2D_PERFORMANCE_REVIEW_DEFINITION.route, baseUrl)
    for (const [key, value] of Object.entries(pageParams ?? {})) {
      url.searchParams.set(key, value)
    }
    url.searchParams.set('review', '1')
    url.searchParams.set('scene', 'empty')
    url.searchParams.set('live2dPerformance', '1')
    return url.href
  },
  assertPage,
}

export const live2dPerformanceReviewNodePlugin = {
  definition: LIVE2D_PERFORMANCE_REVIEW_DEFINITION,
  pageAdapter,
  capabilities: {
    requireObs: true,
    requireInteractive: true,
    requireHostTts: true,
  },
  enableObsAudioMonitoring: true,
  prepareRun: ({ repositoryDir }: { repositoryDir: string }) =>
    TtsHarnessLease.acquire(repositoryDir),
  prepareAttempt: (context: Parameters<TtsHarnessLease['prepareAttempt']>[0], state: unknown) => {
    if (!(state instanceof TtsHarnessLease)) throw new Error('TTS review harness is unavailable')
    return state.prepareAttempt(context, 'billing-to-local')
  },
  artifacts: async (context: Parameters<TtsHarnessLease['artifactsFor']>[0], state: unknown) => {
    if (!(state instanceof TtsHarnessLease)) throw new Error('TTS review harness is unavailable')
    return state.artifactsFor(context)
  },
  cleanupRun: async (_context: unknown, state: unknown) => {
    if (state instanceof TtsHarnessLease) await state.dispose()
  },
}
