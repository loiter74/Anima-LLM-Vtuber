<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '@/types/chat'

const props = defineProps<{ message: ChatMessage }>()

const isUser = props.message.role === 'user'

// For streaming AI messages, wrap text in spans for per-char animation
const displayText = computed(() => {
  return props.message.text
})
</script>

<template>
  <div
    class="flex items-end gap-2 mb-2.5"
    :class="isUser ? 'self-end justify-end' : 'self-start'"
  >
    <!-- Avatar for AI messages -->
    <div
      v-if="!isUser"
      class="w-7 h-7 rounded-full flex items-center justify-center text-[13px] font-bold text-white shrink-0"
      style="background: linear-gradient(135deg, #e879a8, #b14f7e); border: 1px solid rgba(255,255,255,0.15);"
    >
      安
    </div>

    <!-- Bubble -->
    <div
      class="px-[13px] py-[9px] text-sm leading-snug break-words max-w-[78%]"
      :class="[
        isUser
          ? 'bg-c-user-bubble border border-c-blue/30 rounded-2xl rounded-br-[6px]'
          : 'bg-c-ai-bubble border border-c-border-accent rounded-2xl rounded-bl-[6px]',
        message.status === 'streaming' ? 'streaming' : 'animate-[slideUp_0.2s_cubic-bezier(0.16,1,0.3,1)]'
      ]"
    >
      <span v-if="!isUser && message.status === 'streaming'" class="streaming-text">
        <span
          v-for="(char, i) in displayText"
          :key="i"
          class="inline-block"
          :style="{ animationDelay: `${Math.max(0, (displayText.length - 10) - i) * 8}ms` }"
        >{{ char }}</span>
      </span>
      <template v-else>{{ displayText }}</template>
      <span v-if="message.status === 'streaming'" class="inline-block w-0.5 h-4 bg-c-accent ml-0.5 animate-blink align-text-bottom" />
    </div>

    <!-- Timestamp -->
    <span
      class="text-9px text-c-text-muted font-mono"
      :class="isUser ? 'order--1' : ''"
    >
      {{ new Date(message.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}
    </span>
  </div>
</template>

<style scoped>
.streaming {
  animation: none;
}
.animate-blink {
  animation: blink 1s infinite;
}

.streaming-text span {
  animation: charFadeIn 0.15s ease both;
}
</style>
