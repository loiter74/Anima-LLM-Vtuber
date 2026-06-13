<script setup lang="ts">
import { computed } from 'vue'
import type { MemeItem } from '@/stores/memeReview'

const props = defineProps<{
  meme: MemeItem
  feedback?: string
  feedbackVisible?: boolean
}>()

const mechanismLabel = computed(() => props.meme.cognitive_analysis?.humor_mechanism || '—')
const toneLabel = computed(() => props.meme.cognitive_analysis?.emotional_tone || '—')
const fitPercent = computed(() => {
  const s = props.meme.cognitive_analysis?.persona_fit_score
  return s != null ? `${(s * 100).toFixed(0)}%` : '—'
})
const fitScore = computed(() => props.meme.cognitive_analysis?.persona_fit_score ?? 0)

const isGoodFeedback = computed(() => {
  if (!props.feedback) return false
  const g = ['通过', '完整', '不错', '支持', '值得', '合格', '保留', '传播']
  return g.some(w => props.feedback!.includes(w))
})

const voteGlowClass = computed(() => {
  if (!props.feedbackVisible || !props.feedback) return ''
  return isGoodFeedback.value
    ? 'border-c-success/30 shadow-[0_0_8px_rgba(74,222,128,0.3)]'
    : 'border-c-error/30 shadow-[0_0_8px_rgba(248,113,113,0.3)]'
})
</script>

<template>
  <div class="w-full">
    <!-- 梗卡片 -->
    <div class="p-5 rounded-2xl bg-c-card/50 border hover:bg-c-card/60 transition-all" :class="voteGlowClass || 'border-c-border'">
      <div class="text-lg font-medium text-c-text leading-relaxed mb-3">「{{ meme.text }}」</div>
      <div class="flex flex-wrap gap-1.5 mb-3">
        <span class="px-2 py-0.5 text-xs rounded-full bg-c-primary/10 text-c-primary">{{ meme.source_platform }}</span>
        <span v-for="tag in meme.tags.slice(0, 5)" :key="tag" class="px-2 py-0.5 text-xs rounded-full bg-c-bg text-c-text-secondary">{{ tag }}</span>
      </div>
      <div class="grid grid-cols-3 gap-2 text-xs text-c-text-secondary">
        <div><span class="block opacity-50">机制</span><span>{{ mechanismLabel }}</span></div>
        <div><span class="block opacity-50">情感</span><span>{{ toneLabel }}</span></div>
        <div class="flex items-center gap-1.5">
          <span class="opacity-50 shrink-0">匹配</span>
          <svg class="w-4 h-4 shrink-0" viewBox="0 0 36 36">
            <path d="M18 2a16 16 0 1 1 0 32 16 16 0 1 1 0-32" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="3" />
            <path d="M18 2a16 16 0 1 1 0 32 16 16 0 1 1 0-32" fill="none" stroke="currentColor" stroke-width="3"
              stroke-dasharray="100" :stroke-dashoffset="100 - fitScore * 100"
              class="text-c-accent transition-all duration-300"
              stroke-linecap="round" />
          </svg>
          <span>{{ fitPercent }}</span>
        </div>
      </div>
      <a v-if="meme.cognitive_analysis?.source_url" :href="meme.cognitive_analysis.source_url" target="_blank" class="block mt-3 text-xs text-c-primary/60 hover:text-c-primary underline">🔗 B站来源</a>
    </div>

    <!-- AI 反馈 — VTuber 对话气泡 -->
    <Transition name="chat-msg">
      <div v-if="feedbackVisible && feedback" class="mt-3 flex items-start gap-2">
        <div class="w-7 h-7 rounded-full bg-c-primary/20 flex items-center justify-center text-sm shrink-0 mt-0.5">🤖</div>
        <div class="flex flex-col gap-0.5">
          <span class="text-xs text-c-text-secondary/50">Anima</span>
          <div
            class="px-3 py-2 rounded-2xl rounded-tl-sm text-sm leading-relaxed max-w-[320px]"
            :class="isGoodFeedback ? 'bg-green-500/10 text-green-300 border border-green-500/20' : 'bg-red-500/10 text-red-300 border border-red-500/20'"
          >
            {{ feedback }}
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.chat-msg-enter-active { animation: msgIn 0.35s var(--ease-out-expo); }
.chat-msg-leave-active { animation: msgIn 0.25s var(--ease-out-expo) reverse; }
@keyframes msgIn {
  from { opacity: 0; transform: translateX(-8px); }
  to { opacity: 1; transform: translateX(0); }
}
</style>
