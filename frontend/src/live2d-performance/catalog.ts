import type { ReviewDefinition } from '@/review/contracts'
import type {
  Live2DPerformanceAccent,
  Live2DPerformanceBase,
  Live2DPerformancePlanV1,
} from '@/types/socket-events'

export const PERFORMANCE_BASES = [
  'calm',
  'cheerful',
  'concerned',
  'annoyed',
  'surprised',
  'thinking',
  'smug',
] as const satisfies readonly Live2DPerformanceBase[]

export const PERFORMANCE_ACCENTS = [
  'none',
  'brighten',
  'skeptical',
  'startle',
  'sigh',
] as const satisfies readonly Live2DPerformanceAccent[]

export const PERFORMANCE_REVIEW_PLANS: readonly Live2DPerformancePlanV1[] = [
  ...PERFORMANCE_BASES.map((base): Live2DPerformancePlanV1 => ({
    version: 1,
    base,
    intensity: base === 'calm' ? 'subtle' : 'medium',
    accent: 'none',
    source: 'llm',
  })),
  ...PERFORMANCE_ACCENTS.map((accent): Live2DPerformancePlanV1 => ({
    version: 1,
    base: 'calm',
    intensity: 'medium',
    accent,
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
      title: 'Hiyori 七种语义与五种强调',
      observe:
        '确认普通状态平静左右摇摆，七种脸部语义与五种强调从真实音频开始，口型始终可见且每轮结束回到平静。',
      readyTexts: [
        '语义表演控制',
        'calm',
        'cheerful',
        'concerned',
        'annoyed',
        'surprised',
        'thinking',
        'smug',
      ],
      timeline: [],
    },
  ],
} as const satisfies ReviewDefinition<'semantic-catalog', never>
