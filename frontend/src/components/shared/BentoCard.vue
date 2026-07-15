<script setup lang="ts">
import { ref, computed } from 'vue'
import { useScrollTrigger } from '@/composables/useScrollTrigger'
import { useHoverPhysics } from '@/composables/useHoverPhysics'

interface Props {
  /** Column span: 1 or 2 (default: 1) */
  colSpan?: 1 | 2
  /** Row span: 1 or 2 (default: 1) */
  rowSpan?: 1 | 2
  /** Card type for styling */
  type?: 'default' | 'image' | 'stat' | 'chart'
  /** Enable hover physics (default: true) */
  hover?: boolean
  /** Enable scroll reveal (default: true) */
  scrollReveal?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  colSpan: 1,
  rowSpan: 1,
  type: 'default',
  hover: true,
  scrollReveal: true,
})

const cardRef = ref<HTMLElement | null>(null)

// Scroll reveal animation
if (props.scrollReveal) {
  useScrollTrigger(cardRef, {
    start: 'top 85%',
  })
}

// Hover physics
const { onEnter, onLeave } = props.hover
  ? useHoverPhysics(cardRef, { scale: 1.03 })
  : { onEnter: undefined, onLeave: undefined }

// Grid span classes
const spanClasses = computed(() => {
  const classes: string[] = []
  if (props.colSpan === 2) classes.push('col-span-2')
  if (props.rowSpan === 2) classes.push('row-span-2')
  return classes
})

// Type-specific classes
const typeClasses = computed(() => {
  switch (props.type) {
    case 'image':
      return 'overflow-hidden'
    case 'stat':
      return 'flex flex-col items-center justify-center text-center'
    case 'chart':
      return 'p-4'
    default:
      return ''
  }
})
</script>

<template>
  <div
    ref="cardRef"
    class="glass rounded-2xl p-6 transition-colors duration-200 hover:border-c-border-accent will-change-transform"
    :class="[...spanClasses, typeClasses, hover && 'cursor-pointer']"
    @mouseenter="onEnter"
    @mouseleave="onLeave"
  >
    <slot />
  </div>
</template>
