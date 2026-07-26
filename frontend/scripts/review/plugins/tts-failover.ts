import { expect, type Page } from 'playwright/test'
import { TTS_FAILOVER_REVIEW_DEFINITION } from '../../../src/tts-failover/catalog'
import type { AssertionRecord, PageAssertionResult, ReviewPageAdapter } from '../browser'
import { recordAssertion as check } from '../assertions'
import { TtsHarnessLease } from '../tts-harness-lease'

interface Box {
  x: number
  y: number
  width: number
  height: number
}

function boxesIntersect(left: Box, right: Box): boolean {
  return (
    left.x < right.x + right.width &&
    left.x + left.width > right.x &&
    left.y < right.y + right.height &&
    left.y + left.height > right.y
  )
}

async function assertPage(
  page: Page,
  scene: (typeof TTS_FAILOVER_REVIEW_DEFINITION.scenes)[number],
): Promise<PageAssertionResult> {
  const assertions: AssertionRecord[] = []
  const notification = page.getByLabel('TTS 降级接管通知')
  await check(assertions, 'live-shell-visible', () =>
    expect(page.locator('.live-shell')).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'status-rail-visible', () =>
    expect(page.getByLabel('直播状态')).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'danmaku-panel-visible', () =>
    expect(page.getByLabel('实时弹幕')).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'live2d-stage-visible', () =>
    expect(page.locator('#live2dCanvas')).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'takeover-notification-visible', () =>
    expect(notification).toBeVisible({ timeout: 20_000 }),
  )
  for (const text of scene.readyTexts) {
    await check(assertions, `ready-text:${text}`, () =>
      expect(page.getByText(text, { exact: true })).toHaveCount(1),
    )
  }
  await check(assertions, 'audio-complete', () =>
    expect(page.locator('#reviewAudio')).toHaveAttribute('data-complete', 'true', {
      timeout: 30_000,
    }),
  )
  await check(assertions, 'lip-sync-observed', () =>
    expect(notification).toHaveAttribute('data-lip-sync', 'observed', {
      timeout: 30_000,
    }),
  )
  await check(assertions, 'fallback-backend', () => expect(notification).toContainText('fallback'))
  await check(assertions, 'notification-collapsed', () =>
    expect(notification).toHaveAttribute('data-state', 'collapsed', { timeout: 20_000 }),
  )
  await check(assertions, 'notification-in-adaptive-top-gap', async () => {
    const notificationBox = await notification.boundingBox()
    const statusBox = await page.getByLabel('直播状态').boundingBox()
    const danmakuBox = await page.getByLabel('实时弹幕').boundingBox()
    expect(notificationBox).not.toBeNull()
    expect(statusBox).not.toBeNull()
    expect(danmakuBox).not.toBeNull()
    const safeGapLeft = statusBox!.x + statusBox!.width + 12
    const safeGapRight = danmakuBox!.x - 12
    expect(notificationBox!.x).toBeGreaterThanOrEqual(safeGapLeft - 1)
    expect(notificationBox!.x + notificationBox!.width).toBeLessThanOrEqual(safeGapRight + 1)
    expect(notificationBox!.y).toBeGreaterThanOrEqual(27)
    expect(notificationBox!.y).toBeLessThanOrEqual(29)
    expect(notificationBox!.width).toBeLessThanOrEqual(180)
    expect(notificationBox!.height).toBeLessThanOrEqual(32)
    expect(boxesIntersect(notificationBox!, statusBox!)).toBe(false)
    expect(boxesIntersect(notificationBox!, danmakuBox!)).toBe(false)
  })
  const box = await notification.boundingBox()
  return {
    assertions,
    stableLocator: notification,
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
    const url = new URL(TTS_FAILOVER_REVIEW_DEFINITION.route, baseUrl)
    for (const [key, value] of Object.entries(pageParams ?? {})) {
      url.searchParams.set(key, value)
    }
    url.searchParams.set('review', '1')
    url.searchParams.set('scene', 'empty')
    url.searchParams.set('ttsFailover', '1')
    return url.href
  },
  assertPage,
}

export const ttsFailoverReviewNodePlugin = {
  definition: TTS_FAILOVER_REVIEW_DEFINITION,
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
    return state.prepareAttempt(context)
  },
  artifacts: async (context: Parameters<TtsHarnessLease['artifactsFor']>[0], state: unknown) => {
    if (!(state instanceof TtsHarnessLease)) throw new Error('TTS review harness is unavailable')
    return state.artifactsFor(context)
  },
  cleanupRun: async (_context: unknown, state: unknown) => {
    if (state instanceof TtsHarnessLease) await state.dispose()
  },
}
