<script setup lang="ts">
import { ref } from 'vue'
import { useScrollTrigger } from '@/composables/useScrollTrigger'

interface Props {
  /** Gap between cards in px (default: 16) */
  gap?: number
  /** Enable scroll reveal animation (default: true) */
  scrollReveal?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  gap: 16,
  scrollReveal: true,
})

const gridRef = ref<HTMLElement | null>(null)

// Scroll reveal for the entire grid
if (props.scrollReveal) {
  useScrollTrigger(gridRef, {
    start: 'top 90%',
  })
}
</script>

<template>
  <div
    ref="gridRef"
    class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4"
    :style="{ gap: `${gap}px` }"
  >
    <slot />
  </div>
</template>

<style scoped>
.grid {
  grid-auto-flow: dense;
}
</style>
