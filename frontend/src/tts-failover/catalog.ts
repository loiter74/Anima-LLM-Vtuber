import type { ReviewDefinition } from '../review/contracts'

export const TTS_FAILOVER_REVIEW_DEFINITION = {
  id: 'tts-failover',
  contractVersion: 2,
  route: '/live.html',
  viewport: { width: 1080, height: 1920 },
  scenes: [
    {
      id: 'billing-to-local',
      title: 'DashScope 欠费 → 本地语音接管',
      observe: '确认中文自然、远坂凛声线一致、句子完整，且无 BGM、爆音、卡顿或异常停顿。',
      readyTexts: ['云端语音暂不可用', '本地语音已接管'],
      timeline: [],
    },
  ],
} as const satisfies ReviewDefinition<'billing-to-local', never>
