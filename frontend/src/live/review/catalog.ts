import type { BilibiliStatusPayload } from '@/constants/socket-events'
import type { DanmakuItem } from '@/types/chat'
import type { ReviewDefinition, ReviewScene, ScheduledAction } from '@/review/contracts'

export type LiveReviewAction =
  | { type: 'connect' }
  | { type: 'disconnect' }
  | { type: 'status'; payload: BilibiliStatusPayload }
  | { type: 'danmaku'; payload: DanmakuItem }

const REVIEW_TIMESTAMP = Date.UTC(2026, 6, 24, 12, 0, 0) / 1000

const LIVE_STATUS: BilibiliStatusPayload = {
  state: 'live',
  connected: true,
  room_id: 2233,
  desired_room_id: 2233,
  retry_count: 0,
  error_code: null,
  generation_id: 1,
  message: 'Local review',
  updated_at: REVIEW_TIMESTAMP,
}

const DISCONNECTED_STATUS: BilibiliStatusPayload = {
  ...LIVE_STATUS,
  state: 'error',
  connected: false,
  error_code: 'REVIEW_DROP',
  message: 'Local review connection dropped',
  updated_at: REVIEW_TIMESTAMP + 2,
}

const RECONNECTING_STATUS: BilibiliStatusPayload = {
  ...LIVE_STATUS,
  state: 'reconnecting',
  connected: false,
  retry_count: 1,
  error_code: 'REVIEW_DROP',
  message: 'Local review reconnecting',
  updated_at: REVIEW_TIMESTAMP + 4,
}

const RECOVERED_STATUS: BilibiliStatusPayload = {
  ...LIVE_STATUS,
  generation_id: 2,
  message: 'Local review recovered',
  updated_at: REVIEW_TIMESTAMP + 6,
}

const BASELINE_MESSAGES = [
  {
    text: '今晚也一起开心直播吧',
    user_name: '星野',
    user_id: -1,
    timestamp: REVIEW_TIMESTAMP,
  },
  {
    text: '画面和弹幕都准备好了',
    user_name: '小雨',
    user_id: -2,
    timestamp: REVIEW_TIMESTAMP + 1,
  },
] as const satisfies readonly DanmakuItem[]

const TEXT_BOUNDARY_MESSAGES = [
  {
    text: '中文排版检查：晚安，直播间！',
    user_name: '中文观众',
    user_id: -11,
    timestamp: REVIEW_TIMESTAMP,
  },
  {
    text: 'English spacing and wrapping look good.',
    user_name: 'EnglishViewer',
    user_id: -12,
    timestamp: REVIEW_TIMESTAMP + 1,
  },
  {
    text: '太可爱了 ✨🎉💖',
    user_name: 'Emoji🌟观众',
    user_id: -13,
    timestamp: REVIEW_TIMESTAMP + 2,
  },
  {
    text: '长昵称不要挤压时间',
    user_name: '这是一个非常非常长的观众昵称用于边界检查',
    user_id: -14,
    timestamp: REVIEW_TIMESTAMP + 3,
  },
  {
    text: '这是一条用于检查自动换行、面板宽度以及多行内容稳定性的超长弹幕消息，应该完整显示且不会溢出直播画面。',
    user_name: '长文本测试员',
    user_id: -15,
    timestamp: REVIEW_TIMESTAMP + 4,
  },
  {
    text: '1234567890123456789012345678901234567890',
    user_name: '数字观众1234567890',
    user_id: -16,
    timestamp: REVIEW_TIMESTAMP + 5,
  },
] as const satisfies readonly DanmakuItem[]

const SPARSE_MESSAGES = [
  {
    text: '主播晚上好',
    user_name: '早安布丁',
    user_id: -21,
    timestamp: REVIEW_TIMESTAMP,
  },
  {
    text: '今天背景很温馨',
    user_name: '暖灯',
    user_id: -22,
    timestamp: REVIEW_TIMESTAMP + 2,
  },
  {
    text: '刚进来，直播开始了吗',
    user_name: '路过的猫',
    user_id: -23,
    timestamp: REVIEW_TIMESTAMP + 4,
  },
  {
    text: '慢慢聊就好',
    user_name: '云朵',
    user_id: -24,
    timestamp: REVIEW_TIMESTAMP + 6,
  },
] as const satisfies readonly DanmakuItem[]

const BURST_MESSAGES: readonly DanmakuItem[] = Array.from({ length: 18 }, (_, index) => {
  const sequence = String(index + 1).padStart(2, '0')
  return {
    text: `高峰弹幕 ${sequence}`,
    user_name: `观众${sequence}`,
    user_id: -100 - index,
    timestamp: REVIEW_TIMESTAMP + Math.floor(index / 4),
  }
})

const SPECIAL_MESSAGES = [
  {
    text: '路过先打个卡',
    user_name: '夜班巡逻员',
    user_id: -201,
    timestamp: REVIEW_TIMESTAMP,
  },
  {
    text: '送出「摸鱼许可证」×1',
    user_name: '人事部小王',
    user_id: -202,
    timestamp: REVIEW_TIMESTAMP + 1,
    is_gift: true,
  },
  {
    text: '今天的需求真的不会再改了（大概）',
    user_name: '测试组阿灯',
    user_id: -203,
    timestamp: REVIEW_TIMESTAMP + 2,
    is_super_chat: true,
  },
] as const satisfies readonly DanmakuItem[]

const OVERALL_MESSAGES: readonly DanmakuItem[] = [SPARSE_MESSAGES[1], ...SPECIAL_MESSAGES]

const connect = (): LiveReviewAction => ({ type: 'connect' })
const disconnect = (): LiveReviewAction => ({ type: 'disconnect' })
const status = (payload: BilibiliStatusPayload): LiveReviewAction => ({ type: 'status', payload })
const danmaku = (payload: DanmakuItem): LiveReviewAction => ({ type: 'danmaku', payload })
const at = (atMs: number, action: LiveReviewAction): ScheduledAction<LiveReviewAction> => ({
  atMs,
  action,
})
const withLive = (
  timeline: readonly ScheduledAction<LiveReviewAction>[] = [],
): readonly ScheduledAction<LiveReviewAction>[] => [
  at(0, connect()),
  at(0, status(LIVE_STATUS)),
  ...timeline,
]
const messageTexts = (messages: readonly DanmakuItem[]): readonly string[] =>
  messages.map(({ text }) => text)

function defineScene<const Id extends string>(
  scene: ReviewScene<Id, LiveReviewAction>,
): ReviewScene<Id, LiveReviewAction> {
  return scene
}

export const LIVE_REVIEW_SCENES = [
  defineScene({
    id: 'empty',
    title: '启动与空场',
    observe: '检查页面、背景、Live2D、状态栏、竖屏画幅、空弹幕状态与页面溢出。',
    readyTexts: ['服务已连接', '弹幕直播中', 'Live2D 已加载', '等待直播弹幕…'],
    timeline: withLive(),
  }),
  defineScene({
    id: 'baseline',
    title: '基础弹幕',
    observe: '检查少量短消息、计数、时间、入场动画和自动滚动。',
    readyTexts: ['服务已连接', '弹幕直播中', 'Live2D 已加载', ...messageTexts(BASELINE_MESSAGES)],
    timeline: withLive(
      BASELINE_MESSAGES.map((payload, index) => at([250, 800][index], danmaku(payload))),
    ),
  }),
  defineScene({
    id: 'text-boundaries',
    title: '文本边界',
    observe: '检查中英文、Emoji、长昵称、长文本和连续数字的换行及溢出。',
    readyTexts: messageTexts(TEXT_BOUNDARY_MESSAGES),
    timeline: withLive(
      TEXT_BOUNDARY_MESSAGES.map((payload, index) => at(250 + index * 250, danmaku(payload))),
    ),
  }),
  defineScene({
    id: 'sparse',
    title: '稀疏聊天',
    observe: '检查低频弹幕节奏、右上角位置和最终自动滚动。',
    readyTexts: messageTexts(SPARSE_MESSAGES),
    timeline: withLive(
      SPARSE_MESSAGES.map((payload, index) => at([400, 1800, 3400, 5200][index], danmaku(payload))),
    ),
  }),
  defineScene({
    id: 'burst',
    title: '高峰弹幕',
    observe: '检查高峰动画积压、滚动稳定性、隐藏滚轮以及不遮挡 Live2D。',
    readyTexts: ['高峰弹幕 01', '高峰弹幕 18', '18'],
    timeline: withLive(
      BURST_MESSAGES.map((payload, index) => at(250 + index * 80, danmaku(payload))),
    ),
  }),
  defineScene({
    id: 'special',
    title: '礼物与醒目留言',
    observe: '检查礼物、醒目留言标签及保留的趣味员工弹幕。',
    readyTexts: [...messageTexts(SPECIAL_MESSAGES), '礼物', '醒目留言'],
    timeline: withLive(
      SPECIAL_MESSAGES.map((payload, index) => at(250 + index * 550, danmaku(payload))),
    ),
  }),
  defineScene({
    id: 'recovery',
    title: '断线、重连与恢复',
    observe: '依次观察直播中、连接异常、重连中和恢复直播；状态转换为 0/4/8/12 秒。',
    readyTexts: [
      '弹幕直播中',
      '服务已断开',
      '弹幕连接异常',
      '弹幕重连中 · 1',
      '服务已连接',
      '弹幕直播中',
    ],
    timeline: withLive([
      at(4000, disconnect()),
      at(4000, status(DISCONNECTED_STATUS)),
      at(8000, status(RECONNECTING_STATUS)),
      at(12000, connect()),
      at(12000, status(RECOVERED_STATUS)),
    ]),
  }),
  defineScene({
    id: 'overall',
    title: '整体直播感',
    observe: '评估角色位置、背景氛围、弹幕面板占比、礼物层级和整体观看舒适度。',
    readyTexts: messageTexts(OVERALL_MESSAGES),
    timeline: withLive(
      OVERALL_MESSAGES.map((payload, index) => at(400 + index * 800, danmaku(payload))),
    ),
  }),
] as const

export type ReviewSceneId = (typeof LIVE_REVIEW_SCENES)[number]['id']

export const LIVE_REVIEW_SCENE_IDS: readonly ReviewSceneId[] = Object.freeze(
  LIVE_REVIEW_SCENES.map(({ id }) => id),
)

export const LIVE_REVIEW_DEFINITION: ReviewDefinition<ReviewSceneId, LiveReviewAction> = {
  id: 'live',
  contractVersion: 2,
  route: '/live.html',
  viewport: Object.freeze({ width: 1080, height: 1920 }),
  scenes: LIVE_REVIEW_SCENES,
}

export function getLiveReviewScene(sceneId: ReviewSceneId) {
  return LIVE_REVIEW_SCENES.find(({ id }) => id === sceneId)!
}

export function isLiveReviewSceneId(value: string): value is ReviewSceneId {
  return LIVE_REVIEW_SCENE_IDS.some((sceneId) => sceneId === value)
}
