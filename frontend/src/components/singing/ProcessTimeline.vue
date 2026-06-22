<script setup lang="ts">
import { computed } from 'vue'
import type { PipelineStage } from '@/types/singing'

const props = defineProps<{
  currentStage: PipelineStage
  progress: number
  compact?: boolean
}>()

interface TimelineStep {
  stage: PipelineStage
  label: string
  icon: string
}

const steps: TimelineStep[] = [
  { stage: 'downloading', label: '下载音频', icon: '⬇️' },
  { stage: 'separating', label: '人声分离', icon: '🔊' },
  { stage: 'transcribing', label: '歌词识别', icon: '📝' },
  { stage: 'waiting_lyrics', label: '歌词待确认', icon: '⏸' },
  { stage: 'converting', label: '歌声转换', icon: '🎤' },
  { stage: 'mixing', label: '混合输出', icon: '🎛️' },
]

const stageOrder: PipelineStage[] = [
  'downloading', 'separating', 'transcribing',
  'waiting_lyrics', 'converting', 'mixing',
]

function stepStatus(step: TimelineStep): 'done' | 'active' | 'pending' {
  const currentIdx = stageOrder.indexOf(props.currentStage)
  const stepIdx = stageOrder.indexOf(step.stage)
  if (stepIdx < currentIdx && currentIdx !== -1) return 'done'
  if (step.stage === props.currentStage) return 'active'
  return 'pending'
}

const overallPct = computed(() => {
  const currentIdx = stageOrder.indexOf(props.currentStage)
  if (currentIdx === -1) return 0
  return Math.round((currentIdx * 100 + props.progress) / stageOrder.length)
})
</script>

<template>
  <!-- Compact mode: single row with progress bar + icon chain -->
  <div v-if="compact" class="flex items-center gap-2 px-2 py-1.5">
    <!-- Overall progress bar -->
    <div class="flex-1 h-1.5 rounded-full bg-c-accent/20 overflow-hidden">
      <div
        class="h-full bg-c-accent rounded-full transition-all duration-300"
        :style="{ width: `${overallPct}%` }"
      />
    </div>
    <!-- Icon chain -->
    <div class="flex items-center gap-1">
      <template v-for="step in steps" :key="step.stage">
        <span
          class="text-xs transition-all"
          :class="{
            'text-c-accent': stepStatus(step) === 'active',
            'opacity-40': stepStatus(step) === 'pending',
          }"
        >
          <span v-if="stepStatus(step) === 'done'">✅</span>
          <span v-else>{{ step.icon }}</span>
        </span>
        <span v-if="step.stage !== 'mixing'" class="text-c-text-muted text-xs">→</span>
      </template>
    </div>
  </div>

  <!-- Full mode: vertical list -->
  <div v-else class="flex flex-col gap-2 py-2">
    <div
      v-for="step in steps"
      :key="step.stage"
      class="flex items-center gap-3 px-2 py-1.5 rounded-lg text-xs transition-all"
      :class="{
        'opacity-40': stepStatus(step) === 'pending',
        'bg-c-accent/10': stepStatus(step) === 'active',
      }"
    >
      <span class="w-5 text-center">
        <span v-if="stepStatus(step) === 'done'">✅</span>
        <span v-else-if="stepStatus(step) === 'active' && progress > 0">⏳</span>
        <span v-else>{{ step.icon }}</span>
      </span>

      <span
        class="flex-1"
        :class="{
          'text-c-accent font-medium': stepStatus(step) === 'active',
          'text-c-text': stepStatus(step) === 'done',
          'text-c-text-dim': stepStatus(step) === 'pending',
        }"
      >{{ step.label }}</span>

      <span
        v-if="stepStatus(step) === 'active' && progress > 0"
        class="text-c-text-dim"
      >
        {{ Math.round(progress) }}%
      </span>
    </div>
  </div>
</template>
