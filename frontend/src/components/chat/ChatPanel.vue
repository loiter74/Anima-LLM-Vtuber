<script setup lang="ts">
import { computed } from 'vue'
import MessageList from './MessageList.vue'
import InputBar from './InputBar.vue'
import TypingIndicator from './TypingIndicator.vue'
import SpeakingIndicator from './SpeakingIndicator.vue'
import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chat'
import { useMobile } from '@/composables/useMobile'
import { useMemoryStore } from '@/stores/memory'

const { sendText, sendInterrupt, organizeMemory } = useChat()
const store = useChatStore()
const memoryStore = useMemoryStore()
const { isMobile } = useMobile()

const memoryOrganizing = computed(() =>
  memoryStore.job?.status === 'accepted' || memoryStore.job?.status === 'running',
)
const memoryProgress = computed(() => memoryStore.job?.text ?? '')
const memoryProgressPercent = computed(() => memoryStore.job?.progress ?? 0)

async function handleMemoryOrganize(): Promise<void> {
  try {
    await organizeMemory()
  } catch {
    // The memory store exposes the structured error state.
  }
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Compact toolbar -->
    <div class="flex items-center gap-2 px-5 py-4 border-b border-c-border/60 text-xs shrink-0">
      <!-- Memory organize -->
      <button
        class="flex items-center gap-1 px-2 py-1 rounded-lg transition-all"
        :class="memoryOrganizing
          ? 'bg-c-accent/20 text-c-accent pointer-events-none animate-pulse'
          : 'bg-c-bg/40 text-c-text-dim hover:bg-c-panel/50'"
        @click="handleMemoryOrganize"
      >
        <span>🧠</span>
        <span>{{ memoryOrganizing ? '整理中...' : '记忆' }}</span>
      </button>

      <div class="flex-1" />

      <!-- Interrupt button -->
      <button
        v-if="store.lastMessage?.status === 'streaming'"
        class="flex items-center gap-1 px-2 py-1 rounded-lg bg-c-error/15 text-c-error hover:bg-c-error/25 transition-all"
        @click="sendInterrupt"
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
          <rect x="4" y="4" width="16" height="16" rx="2" />
        </svg>
        停止
      </button>
    </div>

    <!-- Memory progress bar with stage detail -->
    <div
      v-if="memoryProgress"
      class="px-5 py-4 bg-c-card/60 border-b border-c-border/40 space-y-2 animate-fade-in shrink-0"
    >
      <div class="flex items-center gap-2 text-xs">
        <span class="animate-pulse">🧠</span>
        <span class="text-c-text-dim flex-1 truncate">{{ memoryProgress }}</span>
        <span class="text-c-text-muted tabular-nums">{{ memoryProgressPercent }}%</span>
      </div>
      <div class="w-full h-1 bg-c-bg rounded-full overflow-hidden">
        <div
          class="h-full bg-gradient-to-r from-c-accent/60 to-c-accent rounded-full transition-all duration-300"
          :style="{ width: memoryProgressPercent + '%' }"
        />
      </div>
    </div>

    <!-- Typing indicator -->
    <TypingIndicator v-if="store.isTyping" />

    <!-- Speaking indicator -->
    <SpeakingIndicator v-if="store.isSpeaking" />

    <!-- Messages -->
    <MessageList class="flex-1" />

    <!-- Input -->
    <InputBar :sendText="sendText" />
  </div>
</template>
