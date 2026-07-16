<script setup lang="ts">
defineEmits<{
  popout: []
}>()
</script>

<template>
  <button
    class="w-7 h-7 flex items-center justify-center rounded-lg bg-c-bg/40 text-c-text-dim hover:text-c-accent hover:bg-c-bg/60 transition-colors"
    title="弹出 Live2D 窗口"
    @click="$emit('popout')"
  >
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
    </svg>
  </button>
</template>
