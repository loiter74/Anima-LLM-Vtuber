<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import MessageBubble from './MessageBubble.vue'
import WelcomeScreen from './WelcomeScreen.vue'

const store = useChatStore()
const listRef = ref<HTMLElement | null>(null)
const userScrolled = ref(false)

function scrollToBottom(): void {
  nextTick(() => {
    if (!listRef.value || userScrolled.value) return
    listRef.value.scrollTop = listRef.value.scrollHeight
  })
}

function handleScroll(): void {
  if (!listRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = listRef.value
  userScrolled.value = scrollHeight - scrollTop - clientHeight > 50
}

watch(() => store.messages.length, scrollToBottom)
watch(() => store.lastMessage?.text, scrollToBottom)
</script>

<template>
  <div
    ref="listRef"
    class="overflow-y-auto px-5 py-4"
    :class="$attrs.class"
    @scroll="handleScroll"
  >
    <!-- Welcome screen (empty state) -->
    <WelcomeScreen v-if="store.messages.length === 0" />

    <!-- Messages -->
    <MessageBubble
      v-for="msg in store.messages"
      :key="msg.id"
      :message="msg"
    />
  </div>
</template>

<style scoped>
::-webkit-scrollbar { width: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }
</style>
