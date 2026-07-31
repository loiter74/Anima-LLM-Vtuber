import { expect, type Locator, type Page } from 'playwright/test'
import { MINECRAFT_GAMEPLAY_REVIEW_DEFINITION } from '../../../src/minecraft-gameplay/catalog'
import type { AssertionRecord, PageAssertionResult, ReviewPageAdapter } from '../browser'
import { recordAssertion as check } from '../assertions'
import { MinecraftHarnessLease } from '../minecraft-harness-lease'
import { MinecraftObsCompositeAdapter } from '../minecraft-obs'
import { minecraftReviewAssertions, minecraftReviewObservations } from '../minecraft-review-client'
import { TtsHarnessLease } from '../tts-harness-lease'
import { ttsReviewAssertions, ttsReviewObservations } from '../tts-review-client'

class MinecraftReviewRunState {
  private disposed = false

  private constructor(
    readonly minecraft: MinecraftHarnessLease,
    readonly tts: TtsHarnessLease,
  ) {}

  static async acquire(repositoryDir: string): Promise<MinecraftReviewRunState> {
    const tts = await TtsHarnessLease.acquire(repositoryDir)
    try {
      const minecraft = await MinecraftHarnessLease.acquire(repositoryDir)
      return new MinecraftReviewRunState(minecraft, tts)
    } catch (error) {
      await tts.dispose()
      throw error
    }
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    await Promise.allSettled([this.minecraft.dispose(), this.tts.dispose()])
  }
}

export function resolveMinecraftStableIndicator(page: Page): Locator {
  return page.locator('.possession-status .status-dot')
}

async function assertPage(page: Page): Promise<PageAssertionResult> {
  const assertions: AssertionRecord[] = []
  const status = page.getByLabel('附身状态')
  const stableIndicator = resolveMinecraftStableIndicator(page)
  await check(assertions, 'minecraft-aperture-visible', () =>
    expect(page.getByLabel('Minecraft 游戏画面')).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'live2d-avatar-visible', () =>
    expect(page.getByLabel('Hiyori 主播')).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'viewer-following-confirmed', () =>
    expect(status).toHaveAttribute('data-confirmed', 'true', { timeout: 30_000 }),
  )
  await check(assertions, 'review-audio-complete', () =>
    expect(page.locator('#reviewAudio')).toHaveAttribute('data-complete', 'true', {
      timeout: 60_000,
    }),
  )
  await check(assertions, 'lip-sync-observed', () =>
    expect(page.locator('.minecraft-review-runtime')).toHaveAttribute('data-lip-sync', 'observed'),
  )
  await check(assertions, 'debug-instrumentation-hidden', async () => {
    await expect(page.getByText('BotDashboard', { exact: false })).toHaveCount(0)
    await expect(page.getByText('表情调试', { exact: false })).toHaveCount(0)
  })
  const box = await stableIndicator.boundingBox()
  return {
    assertions,
    stableLocator: stableIndicator,
    stableRegion: {
      x: box?.x ?? 0,
      y: box?.y ?? 0,
      width: box?.width ?? 1,
      height: box?.height ?? 1,
    },
  }
}

const pageAdapter: ReviewPageAdapter<never> = {
  viewport: { width: 1920, height: 1080 },
  stableMismatchThreshold: 0.25,
  buildUrl({ baseUrl, pageParams }) {
    const url = new URL(MINECRAFT_GAMEPLAY_REVIEW_DEFINITION.route, baseUrl)
    url.searchParams.set('overlay', '1')
    url.searchParams.set('review', '1')
    for (const [key, value] of Object.entries(pageParams ?? {})) {
      url.searchParams.set(key, value)
    }
    return url.href
  },
  assertPage,
}

export const minecraftGameplayReviewNodePlugin = {
  definition: MINECRAFT_GAMEPLAY_REVIEW_DEFINITION,
  pageAdapter,
  capabilities: {
    requireObs: true,
    requireInteractive: true,
    requireHostTts: true,
  },
  enableObsAudioMonitoring: true,
  createObsAdapter: (
    client: import('../obs').ObsClient,
    options: import('../obs').ObsPreviewOptions,
  ) =>
    new MinecraftObsCompositeAdapter(client, {
      ...options,
      gameSourceName: `${options.sceneName} Game Capture`,
      gameAudioSourceName: `${options.sceneName} Game Audio`,
      duckingFilterName: 'Animetta TTS Sidechain',
    }),
  prepareRun: ({ repositoryDir }: { repositoryDir: string }) =>
    MinecraftReviewRunState.acquire(repositoryDir),
  prepareAttempt: async (context: import('../registry').ReviewAttemptContext, state: unknown) => {
    if (!(state instanceof MinecraftReviewRunState)) {
      throw new Error('Minecraft review runtime is unavailable')
    }
    const [gameplay, speech] = await Promise.all([
      state.minecraft.client.run(context),
      state.tts.client.synthesize(context, {
        sceneId: 'minecraft-survival-iron',
        artifactKey: 'broadcast',
        performancePolicy: 'observe',
      }),
    ])
    return {
      pageParams: {
        bindingState: gameplay.payload.binding.binding_state,
        confirmed: String(gameplay.payload.binding.confirmed),
        target: gameplay.payload.binding.target,
        attempt: String(gameplay.payload.binding.attempt),
        reason: gameplay.payload.binding.reason,
        audio: speech.audioUrl,
        mouthTimeline: JSON.stringify(speech.payload.mouth_timeline),
        subtitle: '铁装流程开始，本小姐要认真起来了。先观察周围，再一步一步把装备做齐。',
      },
      assertions: [
        ...minecraftReviewAssertions(gameplay.payload),
        ...ttsReviewAssertions(speech.payload, { includePerformance: false }),
      ],
      observations: [
        ...minecraftReviewObservations(gameplay.payload),
        ...ttsReviewObservations(speech.payload),
      ],
      artifacts: {
        audioWav: speech.audioWav,
        backendReport: speech.backendReport,
        gameplayReport: gameplay.gameplayReport,
      },
    }
  },
  artifacts: async (
    _context: unknown,
    _state: unknown,
    preparation: import('../registry').ReviewAttemptPreparation | void,
  ) => preparation?.artifacts ?? {},
  cleanupRun: async (_context: unknown, state: unknown) => {
    if (state instanceof MinecraftReviewRunState) await state.dispose()
  },
}
