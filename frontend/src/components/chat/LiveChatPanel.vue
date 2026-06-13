<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useDanmakuStore } from '@/stores/danmaku'

const store = useDanmakuStore()
const containerRef = ref<HTMLElement | null>(null)

// Auto-scroll to bottom when new messages arrive
watch(
  () => store.messages.length,
  async () => {
    await nextTick()
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }
)
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header with connection status -->
    <div class="flex items-center gap-2 px-4 py-3 border-b border-c-border/60 shrink-0">
      <span class="text-sm font-medium text-c-text">📺 直播弹幕</span>
      <div class="flex-1" />
      <div class="flex items-center gap-1.5">
        <span
          class="w-2 h-2 rounded-full"
          :class="store.connected ? 'bg-c-success shadow-[0_0_6px_rgba(74,222,128,0.6)]' : 'bg-c-error'"
        />
        <span class="text-xs" :class="store.connected ? 'text-c-success' : 'text-c-error'">
          {{ store.connected ? '已连接' : '已断开' }}
        </span>
      </div>
    </div>

    <!-- Danmaku stream with pop-in animation -->
    <div
      ref="containerRef"
      class="flex-1 overflow-y-auto px-4 py-3 scroll-smooth"
    >
      <div
        v-for="(msg, i) in store.messages"
        :key="i"
        class="danmaku-entry text-sm leading-relaxed break-words py-1"
      >
        <span class="font-medium text-c-accent">{{ msg.user_name }}</span>
        <span class="text-c-text-dim mx-1">:</span>
        <span class="text-c-text">{{ msg.text }}</span>
      </div>

      <!-- Empty state -->
      <div
        v-if="store.messages.length === 0"
        class="flex flex-col items-center justify-center h-full text-c-text-dim text-sm gap-2"
      >
        <span class="text-2xl">💬</span>
        <span>等待弹幕中...</span>
        <span v-if="!store.connected" class="text-xs text-c-warning">
          ⚠️ 未连接，请先在设置中配置直播间
        </span>
      </div>
    </div>

    <!-- Message count -->
    <div class="px-4 py-2 border-t border-c-border/30 text-10px text-c-text-muted text-center shrink-0">
      共 {{ store.messageCount }} 条弹幕
    </div>
  </div>
</template>

<style scoped>
.danmaku-entry {
  animation: popIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  will-change: transform, opacity;
}

@keyframes popIn {
  0% {
    transform: translateY(10px);
    opacity: 0;
  }
  100% {
    transform: translateY(0);
    opacity: 1;
  }
}

::-webkit-scrollbar { width: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }
</style>
