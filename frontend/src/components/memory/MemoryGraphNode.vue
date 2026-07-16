<script setup lang="ts">
/**
 * MemoryGraphNode — individual node rendered inside SVG.
 *
 * Position (x, y) is set via transform on the <g> group.
 * Circle fill comes from CATEGORY_COLORS, radius from importance (8-32px).
 * Label is truncated to 20 chars.
 */
import { computed } from 'vue'
import type { MemoryNode } from '@/types/memoryGraph'
import { CATEGORY_COLORS } from '@/types/memoryGraph'

const props = defineProps<{
  node: MemoryNode
  dimmed?: boolean
  selected?: boolean
}>()

const emit = defineEmits<{
  click: [node: MemoryNode]
  dragStart: [node: MemoryNode, event: MouseEvent]
}>()

/** Map importance (0-1) to radius (8-32px) */
const radius = computed(() => 8 + props.node.importance * 24)

/** Fill color from category */
const fillColor = computed(() => CATEGORY_COLORS[props.node.category] ?? 'var(--c-text-dim)')

/** Truncate label to 20 chars */
const truncatedLabel = computed(() => {
  const label = props.node.label
  return label.length > 20 ? label.slice(0, 18) + '…' : label
})

/** Transform string for d3-force positioning */
const transform = computed(() => `translate(${props.node.x ?? 0}, ${props.node.y ?? 0})`)

function handleClick() {
  emit('click', props.node)
}

function handleMouseDown(event: MouseEvent) {
  emit('dragStart', props.node, event)
}
</script>

<template>
  <g
    class="graph-node"
    :class="{ dimmed, selected }"
    :transform="transform"
    @click="handleClick"
    @mousedown.prevent="handleMouseDown"
  >
    <!-- Outer glow for selected -->
    <circle
      v-if="selected"
      :r="radius + 4"
      :fill="fillColor"
      opacity="0.15"
      class="pointer-events-none"
    />

    <!-- Main circle -->
    <circle :r="radius" :fill="fillColor" opacity="0.85" />

    <!-- Label below circle -->
    <text class="graph-node-label" :y="radius + 14">
      {{ truncatedLabel }}
    </text>
  </g>
</template>
