<script setup lang="ts">
import { ref } from 'vue'
import { unlockAudioPlayback } from '@/components/live2d/useAudioPlayback'
import { useMobile } from '@/composables/useMobile'
import VoiceButton from './VoiceButton.vue'

const { sendText } = defineProps<{ sendText: (text: string) => void }>()
const { isMobile } = useMobile()
const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function handleInput(): void {
  if (!textareaRef.value) return
  textareaRef.value.style.height = 'auto'
  textareaRef.value.style.height = Math.min(textareaRef.value.scrollHeight, 120) + 'px'
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function sendMessage(): void {
  const text = inputText.value.trim()
  if (!text) return
  sendText(text)
  inputText.value = ''
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
  }
}
</script>

<template>
  <div
    data-testid="chat-input-bar"
    class="border border-c-border rounded-lg backdrop-blur-md flex items-center focus-within:border-c-border-accent focus-within:shadow-[0_0_0_3px_var(--c-accent-soft)]"
    style="background: rgba(36, 21, 56, 0.35); touch-action: manipulation"
    :class="
      isMobile
        ? 'mobile-input-bar gap-3 px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] w-full'
        : 'gap-2.5 pl-5 pr-4 py-4'
    "
    @pointerdown.capture="unlockAudioPlayback"
    @keydown.capture="unlockAudioPlayback"
  >
    <textarea
      ref="textareaRef"
      v-model="inputText"
      class="flex-1 bg-transparent border-0 outline-none text-sm text-c-text placeholder-c-text-muted resize-none min-h-10 max-h-30"
      :class="isMobile ? 'mobile-input-textarea leading-snug' : ''"
      placeholder="输入消息..."
      rows="1"
      @input="handleInput"
      @keydown="handleKeydown"
    />
    <VoiceButton :class="isMobile ? '!w-12 !h-12' : ''" />
    <button
      class="bg-c-accent hover:bg-c-accent-hover text-white rounded-lg flex items-center justify-center transition-all duration-200 disabled:bg-c-card disabled:text-c-text-muted disabled:cursor-not-allowed"
      :class="isMobile ? 'w-12 h-12' : 'w-8 h-8'"
      :disabled="!inputText.trim()"
      @click="sendMessage"
    >
      <svg width="14" height="14" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
      </svg>
    </button>
  </div>
</template>
