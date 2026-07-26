import { describe, expect, it, vi } from 'vitest'
import { Events } from '@/constants/socket-events'
import { createReviewSocket, resolveReviewRequest, type ReviewClock } from '../review-socket'

function manualClock() {
  let nextId = 1
  const callbacks = new Map<number, () => void>()
  const delays: number[] = []
  const clock: ReviewClock = {
    setTimeout(callback, delayMs) {
      const id = nextId++
      delays.push(delayMs)
      callbacks.set(id, callback)
      return id
    },
    clearTimeout(id) {
      callbacks.delete(id)
    },
  }
  return {
    clock,
    callbacks,
    delays,
    flush(): void {
      while (callbacks.size > 0) {
        const [id, callback] = callbacks.entries().next().value!
        callbacks.delete(id)
        callback()
      }
    },
  }
}

describe('review request resolution', () => {
  it('exports one ordered typed catalog for browser and runner consumers', async () => {
    const reviewModule = (await import('../review-socket')) as unknown as {
      LIVE_REVIEW_SCENES?: ReadonlyArray<{
        id: string
        readyTexts: readonly string[]
        timeline: ReadonlyArray<{ atMs: number; action: { type: string } }>
      }>
      LIVE_REVIEW_SCENE_IDS?: readonly string[]
    }

    expect(reviewModule.LIVE_REVIEW_SCENE_IDS).toEqual([
      'empty',
      'baseline',
      'text-boundaries',
      'sparse',
      'burst',
      'special',
      'recovery',
      'overall',
    ])
    const scenes = reviewModule.LIVE_REVIEW_SCENES
    expect(scenes?.map(({ id }) => id)).toEqual(reviewModule.LIVE_REVIEW_SCENE_IDS)
    expect(
      scenes?.every(({ timeline }) =>
        timeline.every(({ action }) =>
          ['connect', 'disconnect', 'status', 'danmaku'].includes(action.type),
        ),
      ),
    ).toBe(true)
    expect(scenes?.find(({ id }) => id === 'text-boundaries')?.readyTexts).toContain(
      '中文排版检查：晚安，直播间！',
    )
    expect(scenes?.find(({ id }) => id === 'sparse')?.readyTexts).toEqual([
      '主播晚上好',
      '今天背景很温馨',
      '刚进来，直播开始了吗',
      '慢慢聊就好',
    ])
  })

  it('selects the requested review scene', () => {
    expect(resolveReviewRequest(new URLSearchParams('review=1&scene=empty'))).toEqual({
      enabled: true,
      sceneId: 'empty',
    })
  })

  it('selects the text-boundaries review scene', () => {
    expect(resolveReviewRequest(new URLSearchParams('review=1&scene=text-boundaries'))).toEqual({
      enabled: true,
      sceneId: 'text-boundaries',
    })
  })

  it('selects the sparse and burst traffic scenes', () => {
    expect(resolveReviewRequest(new URLSearchParams('review=1&scene=sparse'))).toEqual({
      enabled: true,
      sceneId: 'sparse',
    })
    expect(resolveReviewRequest(new URLSearchParams('review=1&scene=burst'))).toEqual({
      enabled: true,
      sceneId: 'burst',
    })
  })

  it('selects the special message scene', () => {
    expect(resolveReviewRequest(new URLSearchParams('review=1&scene=special'))).toEqual({
      enabled: true,
      sceneId: 'special',
    })
  })

  it('selects the recovery scene', () => {
    expect(resolveReviewRequest(new URLSearchParams('review=1&scene=recovery'))).toEqual({
      enabled: true,
      sceneId: 'recovery',
    })
  })

  it('selects the overall composition scene', () => {
    expect(resolveReviewRequest(new URLSearchParams('review=1&scene=overall'))).toEqual({
      enabled: true,
      sceneId: 'overall',
    })
  })

  it('maps the legacy demo entry to the baseline scene', () => {
    expect(resolveReviewRequest(new URLSearchParams('demo=1'))).toEqual({
      enabled: true,
      sceneId: 'baseline',
    })
  })

  it('falls back to baseline and warns for an unknown scene', () => {
    const warn = vi.fn()

    expect(resolveReviewRequest(new URLSearchParams('review=1&scene=unknown'), warn)).toEqual({
      enabled: true,
      sceneId: 'baseline',
    })
    expect(warn).toHaveBeenCalledWith('Unknown livestream review scene "unknown"; using baseline')
  })
})

describe('in-memory review socket', () => {
  it('emits canonical baseline events in deterministic order', () => {
    const { clock, flush } = manualClock()
    const socket = createReviewSocket('baseline', clock)
    const observed: Array<{ event: string; value?: unknown }> = []

    socket.on('connect', () => observed.push({ event: 'connect' }))
    socket.on(Events.BILIBILI.DANMAKU_STATUS, (value) =>
      observed.push({ event: Events.BILIBILI.DANMAKU_STATUS, value }),
    )
    socket.on(Events.BILIBILI.DANMAKU, (value) =>
      observed.push({ event: Events.BILIBILI.DANMAKU, value }),
    )

    socket.start()
    flush()

    expect(observed.map(({ event }) => event)).toEqual([
      'connect',
      Events.BILIBILI.DANMAKU_STATUS,
      Events.BILIBILI.DANMAKU,
      Events.BILIBILI.DANMAKU,
    ])
    expect(observed[1].value).toEqual(
      expect.objectContaining({ state: 'live', connected: true, message: 'Local review' }),
    )
    expect(observed.slice(2).map(({ value }) => value)).toEqual([
      expect.objectContaining({ user_name: '星野', text: '今晚也一起开心直播吧' }),
      expect.objectContaining({ user_name: '小雨', text: '画面和弹幕都准备好了' }),
    ])
  })

  it('keeps the empty scene free of danmaku', () => {
    const { clock, flush } = manualClock()
    const socket = createReviewSocket('empty', clock)
    const danmaku = vi.fn()
    socket.on(Events.BILIBILI.DANMAKU, danmaku)

    socket.start()
    flush()

    expect(danmaku).not.toHaveBeenCalled()
  })

  it('emits deterministic fixtures for every text boundary', () => {
    const { clock, flush } = manualClock()
    const socket = createReviewSocket('text-boundaries', clock)
    const messages: unknown[] = []
    socket.on(Events.BILIBILI.DANMAKU, (value) => messages.push(value))

    socket.start()
    flush()

    expect(messages).toEqual([
      expect.objectContaining({
        user_name: '中文观众',
        text: '中文排版检查：晚安，直播间！',
      }),
      expect.objectContaining({
        user_name: 'EnglishViewer',
        text: 'English spacing and wrapping look good.',
      }),
      expect.objectContaining({
        user_name: 'Emoji🌟观众',
        text: '太可爱了 ✨🎉💖',
      }),
      expect.objectContaining({
        user_name: '这是一个非常非常长的观众昵称用于边界检查',
        text: '长昵称不要挤压时间',
      }),
      expect.objectContaining({
        user_name: '长文本测试员',
        text: '这是一条用于检查自动换行、面板宽度以及多行内容稳定性的超长弹幕消息，应该完整显示且不会溢出直播画面。',
      }),
      expect.objectContaining({
        user_name: '数字观众1234567890',
        text: '1234567890123456789012345678901234567890',
      }),
    ])
  })

  it('paces the sparse scene as four separated chat messages', () => {
    const { clock, delays, flush } = manualClock()
    const socket = createReviewSocket('sparse', clock)
    const messages: unknown[] = []
    socket.on(Events.BILIBILI.DANMAKU, (value) => messages.push(value))

    socket.start()
    expect(delays).toEqual([0, 0, 400, 1800, 3400, 5200])
    flush()

    expect(messages).toEqual([
      expect.objectContaining({ user_name: '早安布丁', text: '主播晚上好' }),
      expect.objectContaining({ user_name: '暖灯', text: '今天背景很温馨' }),
      expect.objectContaining({ user_name: '路过的猫', text: '刚进来，直播开始了吗' }),
      expect.objectContaining({ user_name: '云朵', text: '慢慢聊就好' }),
    ])
  })

  it('paces the burst scene as a deterministic high-volume peak', () => {
    const { clock, delays, flush } = manualClock()
    const socket = createReviewSocket('burst', clock)
    const messages: unknown[] = []
    socket.on(Events.BILIBILI.DANMAKU, (value) => messages.push(value))

    socket.start()
    expect(delays).toHaveLength(20)
    expect(delays.slice(2)).toEqual(Array.from({ length: 18 }, (_, index) => 250 + index * 80))
    flush()

    expect(messages).toHaveLength(18)
    expect(messages[0]).toEqual(
      expect.objectContaining({ user_name: '观众01', text: '高峰弹幕 01' }),
    )
    expect(messages[17]).toEqual(
      expect.objectContaining({ user_name: '观众18', text: '高峰弹幕 18' }),
    )
  })

  it('emits ordinary, gift, and super-chat fixtures for the special scene', () => {
    const { clock, flush } = manualClock()
    const socket = createReviewSocket('special', clock)
    const messages: unknown[] = []
    socket.on(Events.BILIBILI.DANMAKU, (value) => messages.push(value))

    socket.start()
    flush()

    expect(messages).toEqual([
      expect.objectContaining({ user_name: '夜班巡逻员', text: '路过先打个卡' }),
      expect.objectContaining({
        user_name: '人事部小王',
        text: '送出「摸鱼许可证」×1',
        is_gift: true,
      }),
      expect.objectContaining({
        user_name: '测试组阿灯',
        text: '今天的需求真的不会再改了（大概）',
        is_super_chat: true,
      }),
    ])
  })

  it('emits a deterministic live, disconnect, reconnect, and recovery sequence', () => {
    const { clock, delays, flush } = manualClock()
    const socket = createReviewSocket('recovery', clock)
    const observed: Array<{ event: string; value?: unknown }> = []

    socket.on('connect', () => observed.push({ event: 'connect' }))
    socket.on('disconnect', () => observed.push({ event: 'disconnect' }))
    socket.on(Events.BILIBILI.DANMAKU_STATUS, (value) =>
      observed.push({ event: Events.BILIBILI.DANMAKU_STATUS, value }),
    )

    socket.start()
    expect(delays).toEqual([0, 0, 4000, 4000, 8000, 12000, 12000])
    flush()

    expect(observed.map(({ event }) => event)).toEqual([
      'connect',
      Events.BILIBILI.DANMAKU_STATUS,
      'disconnect',
      Events.BILIBILI.DANMAKU_STATUS,
      Events.BILIBILI.DANMAKU_STATUS,
      'connect',
      Events.BILIBILI.DANMAKU_STATUS,
    ])
    expect(
      observed
        .filter(({ event }) => event === Events.BILIBILI.DANMAKU_STATUS)
        .map(({ value }) => value),
    ).toEqual([
      expect.objectContaining({ state: 'live', connected: true, retry_count: 0 }),
      expect.objectContaining({ state: 'error', connected: false, error_code: 'REVIEW_DROP' }),
      expect.objectContaining({ state: 'reconnecting', connected: false, retry_count: 1 }),
      expect.objectContaining({ state: 'live', connected: true, retry_count: 0 }),
    ])
  })

  it('combines ordinary chat, gift, and super-chat fixtures for the overall scene', () => {
    const { clock, delays, flush } = manualClock()
    const socket = createReviewSocket('overall', clock)
    const messages: unknown[] = []
    socket.on(Events.BILIBILI.DANMAKU, (value) => messages.push(value))

    socket.start()
    expect(delays).toEqual([0, 0, 400, 1200, 2000, 2800])
    flush()

    expect(messages).toEqual([
      expect.objectContaining({ user_name: '暖灯', text: '今天背景很温馨' }),
      expect.objectContaining({ user_name: '夜班巡逻员', text: '路过先打个卡' }),
      expect.objectContaining({
        user_name: '人事部小王',
        text: '送出「摸鱼许可证」×1',
        is_gift: true,
      }),
      expect.objectContaining({
        user_name: '测试组阿灯',
        text: '今天的需求真的不会再改了（大概）',
        is_super_chat: true,
      }),
    ])
  })

  it('clears scheduled scene events on dispose', () => {
    const { clock, callbacks } = manualClock()
    const socket = createReviewSocket('baseline', clock)

    socket.start()
    expect(callbacks.size).toBeGreaterThan(0)

    socket.dispose()

    expect(callbacks.size).toBe(0)
  })
})
