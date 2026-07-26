import { expect, type Page } from 'playwright/test'
import type { ReviewPageAdapter } from '../browser'
import type { AssertionRecord, PageAssertionResult } from '../browser'
import { recordAssertion as check } from '../assertions'
import { LIVE_REVIEW_DEFINITION, type LiveReviewAction } from '../../../src/live/review/catalog'

async function assertLivePage(
  page: Page,
  scene: (typeof LIVE_REVIEW_DEFINITION.scenes)[number],
): Promise<PageAssertionResult> {
  const assertions: AssertionRecord[] = []
  const live2d = page.getByLabel('Live2D 舞台')
  const panel = page.getByLabel('实时弹幕')
  const statusRail = page.getByLabel('直播状态')
  await check(assertions, 'live2d-visible', () => expect(live2d).toBeVisible({ timeout: 20_000 }))
  await check(assertions, 'danmaku-panel-visible', () =>
    expect(panel).toBeVisible({ timeout: 20_000 }),
  )
  await check(assertions, 'status-rail-visible', () =>
    expect(statusRail).toBeVisible({ timeout: 20_000 }),
  )
  for (const text of scene.readyTexts) {
    await check(assertions, `ready-text:${text}`, () =>
      expect(page.getByText(text, { exact: true }).last()).toBeVisible({ timeout: 20_000 }),
    )
  }

  const expectedMessages = scene.timeline.filter(({ action }) => action.type === 'danmaku').length
  await check(assertions, 'message-count', () =>
    expect(page.locator('#messageCount')).toHaveText(String(expectedMessages)),
  )
  await check(assertions, 'collapse-control-absent', () =>
    expect(page.locator('#togglePanel')).toHaveCount(0),
  )

  const metrics = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight,
  }))
  await check(assertions, 'viewport-1080x1920', () => {
    expect(metrics).toEqual({
      innerWidth: 1080,
      innerHeight: 1920,
      scrollWidth: 1080,
      scrollHeight: 1920,
    })
  })

  const panelBox = await panel.boundingBox()
  const statusBox = await statusRail.boundingBox()
  await check(assertions, 'panel-top-right', () => {
    expect(panelBox).not.toBeNull()
    expect(statusBox).not.toBeNull()
    expect(panelBox!.x).toBeGreaterThan(1080 / 2)
    expect(Math.abs(panelBox!.y - statusBox!.y)).toBeLessThanOrEqual(2)
    expect(panelBox!.x + panelBox!.width).toBeLessThanOrEqual(1080 - 27)
  })
  await check(assertions, 'panel-avoids-live2d-focus', () => {
    expect(panelBox).not.toBeNull()
    expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(1920 * 0.4)
  })

  const scroll = await page.locator('#danmakuList').evaluate((element) => {
    const html = element as HTMLElement
    return {
      scrollbarWidth: getComputedStyle(html).scrollbarWidth,
      atBottom: html.scrollTop + html.clientHeight >= html.scrollHeight - 1,
    }
  })
  await check(assertions, 'scrollbar-hidden', () => expect(scroll.scrollbarWidth).toBe('none'))
  await check(assertions, 'auto-scroll-at-bottom', () => expect(scroll.atBottom).toBe(true))

  const stableRegion = {
    x: panelBox?.x ?? 0,
    y: panelBox?.y ?? 0,
    width: panelBox?.width ?? 1,
    height: panelBox?.height ?? 1,
  }
  return { assertions, stableLocator: panel, stableRegion }
}

export const liveReviewNodePlugin: {
  definition: typeof LIVE_REVIEW_DEFINITION
  pageAdapter: ReviewPageAdapter<LiveReviewAction>
} = {
  definition: LIVE_REVIEW_DEFINITION,
  pageAdapter: {
    forbiddenRequestPatterns: [/\/socket\.io\//],
    buildUrl({ baseUrl, runId, sceneId, attempt }) {
      const url = new URL(LIVE_REVIEW_DEFINITION.route, baseUrl)
      url.searchParams.set('review', '1')
      url.searchParams.set('scene', sceneId)
      url.searchParams.set('attempt', `${runId}-${attempt}`)
      url.searchParams.set('bg', '温馨直播室.png')
      url.searchParams.set('bgOpacity', '0.9')
      url.searchParams.set('bgPosition', 'center')
      return url.href
    },
    assertPage: assertLivePage,
  },
}
