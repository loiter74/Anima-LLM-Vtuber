import { expect, type Page } from 'playwright/test'
import { LIVE2D_PERFORMANCE_REVIEW_DEFINITION } from '../../../src/review/live2d-performance/catalog'
import type { AssertionRecord, PageAssertionResult, ReviewPageAdapter } from '../browser'
import { recordAssertion as check } from '../assertions'
import { TtsHarnessLease } from '../tts-harness-lease'
import { ttsReviewAssertions, type PreparedTtsReviewSample } from '../tts-review-client'

const PERFORMANCE_SAMPLES = [
  { base: 'calm', sceneId: 'live2d-calm' },
  { base: 'annoyed', sceneId: 'live2d-annoyed' },
  { base: 'surprised', sceneId: 'live2d-surprised' },
] as const

async function assertPage(page: Page): Promise<PageAssertionResult> {
  const assertions: AssertionRecord[] = []
  const panel = page.locator('.live2d-performance-review')
  await check(assertions, 'live2d-stage-visible', () =>
    expect(page.getByLabel('Live2D 舞台')).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'performance-instrumentation-hidden', () =>
    expect(panel).toBeHidden({ timeout: 20_000 }),
  )
  await check(assertions, 'semantic-sequence-complete', () =>
    expect(panel).toHaveAttribute('data-complete', 'true', { timeout: 150_000 }),
  )
  await check(assertions, 'lip-sync-observed', () =>
    expect(panel).toHaveAttribute('data-lip-sync', 'observed'),
  )
  await check(assertions, 'interruption-returned-to-calm', () =>
    expect(panel).toHaveAttribute('data-interruption', 'observed'),
  )
  await check(assertions, 'activation-delay-observed', () =>
    expect(panel).toHaveAttribute('data-activation-observed', 'true'),
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
    requireHardwareWebgl: true,
  },
  enableObsAudioMonitoring: true,
  prepareRun: ({ repositoryDir }: { repositoryDir: string }) =>
    TtsHarnessLease.acquire(repositoryDir),
  prepareAttempt: async (context: import('../registry').ReviewAttemptContext, state: unknown) => {
    if (!(state instanceof TtsHarnessLease)) throw new Error('TTS review harness is unavailable')
    const prepared: Array<{
      base: (typeof PERFORMANCE_SAMPLES)[number]['base']
      synthesis: PreparedTtsReviewSample
    }> = []
    for (const descriptor of PERFORMANCE_SAMPLES) {
      prepared.push({
        base: descriptor.base,
        synthesis: await state.client.synthesize(context, {
          sceneId: descriptor.sceneId,
          artifactKey: descriptor.base,
        }),
      })
    }
    const calm = prepared.find(({ base }) => base === 'calm')!.synthesis
    return {
      pageParams: {
        performanceSamples: JSON.stringify(
          prepared.map(({ base, synthesis }) => ({
            base,
            audio: synthesis.audioUrl,
            mouthTimeline: synthesis.payload.mouth_timeline,
          })),
        ),
      },
      assertions: prepared.flatMap(({ base, synthesis }) =>
        ttsReviewAssertions(synthesis.payload).map((assertion) => ({
          ...assertion,
          name: `${base}:${assertion.name}`,
        })),
      ),
      observations: [
        { name: 'performance_sample_count', value: prepared.length },
        {
          name: 'performance_semantics',
          value: PERFORMANCE_SAMPLES.map(({ base }) => base).join(','),
        },
      ],
      artifacts: {
        audioWav: calm.audioWav,
        backendReport: calm.backendReport,
        audioSamples: Object.fromEntries(
          prepared.map(({ base, synthesis }) => [
            base,
            {
              audioWav: synthesis.audioWav,
              backendReport: synthesis.backendReport,
            },
          ]),
        ),
      },
    }
  },
  artifacts: async (
    _context: unknown,
    _state: unknown,
    preparation: import('../registry').ReviewAttemptPreparation | void,
  ) => preparation?.artifacts ?? {},
  cleanupRun: async (_context: unknown, state: unknown) => {
    if (state instanceof TtsHarnessLease) await state.dispose()
  },
}
