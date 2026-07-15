<script setup lang="ts">
import { computed } from 'vue'
import { useVoice } from '@/composables/useVoice'

const { isRecording, volume, toggle } = useVoice()
const volumePercent = computed(() => Math.min(100, Math.round(volume.value * 500)))
</script>

<template>
  <button
    class="relative w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-200"
    :class="
      isRecording
        ? 'bg-c-accent text-white animate-pulse'
        : 'bg-c-panel/60 border border-c-border text-c-text-dim hover:bg-c-accent-soft hover:text-c-accent'
    "
    @click="toggle"
  >
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
    </svg>

    <!-- Volume bar -->
    <div
      v-if="isRecording"
      class="absolute -bottom-1 left-1/2 -translate-x-1/2 w-6 h-1 bg-c-bg rounded-full overflow-hidden"
    >
      <div
        class="h-full bg-c-success rounded-full transition-all duration-150"
        :style="{ width: volumePercent + '%' }"
      />
    </div>
  </button>
</template>
