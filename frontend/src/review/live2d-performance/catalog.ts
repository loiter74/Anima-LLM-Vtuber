import type { ReviewDefinition } from '@/review/contracts'
import {
  LIVE2D_PERFORMANCE_BASES,
  type Live2DPerformancePlanV1,
} from '@/shared/live2d/performanceContract'

export const PERFORMANCE_BASES = LIVE2D_PERFORMANCE_BASES
export const PERFORMANCE_ACCENTS = [] as const

export const PERFORMANCE_REVIEW_PLANS: readonly Live2DPerformancePlanV1[] = [
  ...LIVE2D_PERFORMANCE_BASES.map((base): Live2DPerformancePlanV1 => ({
    version: 1,
    base,
    intensity: base === 'calm' ? 'subtle' : 'medium',
    accent: 'none',
    source: 'llm',
  })),
]

export const LIVE2D_PERFORMANCE_REVIEW_DEFINITION = {
  id: 'live2d-performance',
  contractVersion: 1,
  route: '/live.html',
  viewport: { width: 1080, height: 1920 },
  scenes: [
    {
      id: 'semantic-catalog',
      title: '虹色 Mao 三种关键表情',
      observe:
        '确认日常、吐槽和惊讶三种关键表情与对应中文语音同步，口型始终可见且每轮结束回到平静。',
      readyTexts: ['服务已连接', '弹幕直播中', 'Live2D 已加载'],
      timeline: [],
    },
  ],
} as const satisfies ReviewDefinition<'semantic-catalog', never>
