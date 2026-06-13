<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import MessageList from './MessageList.vue'
import InputBar from './InputBar.vue'
import TypingIndicator from './TypingIndicator.vue'
import SpeakingIndicator from './SpeakingIndicator.vue'
import { useChat } from '@/composables/useChat'
import { useChatStore } from '@/stores/chat'
import { getSocket } from '@/composables/useSocket'
import { useMobile } from '@/composables/useMobile'

const { sendText, sendInterrupt, organizeMemory } = useChat()
const store = useChatStore()
const { isMobile } = useMobile()

// Memory organize progress
const memoryProgress = ref('')
const memoryProgressPercent = ref(0)

// Memory progress listener (via socket)
onMounted(() => {
  const socket = getSocket()
  if (!socket) return
  socket.on('memory.organize.progress', (data: any) => {
    memoryProgress.value = data.text || ''
    memoryProgressPercent.value = data.progress || 0
  })
})

onUnmounted(() => {
  const socket = getSocket()
  if (!socket) return
  socket.off('memory.organize.progress')
})

async function handleMemoryOrganize(): Promise<void> {
  await organizeMemory()
}

// Reset memory progress when result comes
watch(() => store.memoryOrganizing, (organizing) => {
  if (!organizing) {
    memoryProgress.value = ''
    memoryProgressPercent.value = 0
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Compact toolbar -->
    <div class="flex items-center gap-2 px-5 py-4 border-b border-c-border/60 text-xs shrink-0">
      <!-- Memory organize -->
      <button
        class="flex items-center gap-1 px-2 py-1 rounded-lg transition-all"
        :class="store.memoryOrganizing
          ? 'bg-c-accent/20 text-c-accent pointer-events-none animate-pulse'
          : 'bg-c-bg/40 text-c-text-dim hover:bg-c-panel/50'"
        @click="handleMemoryOrganize"
      >
        <span>🧠</span>
        <span>{{ store.memoryOrganizing ? '整理中...' : '记忆' }}</span>
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
