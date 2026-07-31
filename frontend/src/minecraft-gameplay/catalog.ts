import type { ReviewDefinition } from '../review/contracts'

export const MINECRAFT_GAMEPLAY_REVIEW_DEFINITION = {
  id: 'minecraft-gameplay',
  contractVersion: 1,
  route: '/minecraft-gameplay.html',
  viewport: { width: 1920, height: 1080 },
  scenes: [
    {
      id: 'survival-iron',
      title: 'Minecraft 主播完整铁装',
      observe:
        '确认真实游戏画面持续变化、Hiyori 位于右下、附身状态已确认，TTS、口型、字幕与游戏音频均正常且没有重复播放。',
      readyTexts: ['已附身 LUN077 → AnimettaBot'],
      timeline: [],
    },
  ],
} as const satisfies ReviewDefinition<'survival-iron', never>
