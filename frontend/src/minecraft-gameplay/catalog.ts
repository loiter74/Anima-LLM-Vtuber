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
        '确认真实游戏画面持续变化、虹色 Mao 位于右下、附身状态已确认，TTS、口型、字幕与游戏音频均正常且没有重复播放。',
      readyTexts: ['已附身 LUN077 → AnimettaBot'],
      timeline: [],
    },
    {
      id: 'adaptive-mission',
      title: 'Minecraft 自适应任务证据时间线',
      observe:
        '确认 LUN077 已真实附身 AnimettaBot，右侧证据轨按同一 run/mission 推进，场景布置与 bot 自主获得的结果明确分隔。',
      readyTexts: ['已附身 LUN077 → AnimettaBot', '场景布置不计入任务成绩'],
      timeline: [],
    },
  ],
} as const satisfies ReviewDefinition<'survival-iron' | 'adaptive-mission', never>
