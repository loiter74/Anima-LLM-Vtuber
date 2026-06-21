<script setup lang="ts">
/**
 * MemoryGraphEdge — line connecting two nodes in SVG.
 *
 * Stroke color from RELATION_COLORS, width from weight (1-4px), opacity 0.4.
 * Points (x1,y1,x2,y2) are set dynamically by the parent (d3-force updates).
 */
import { computed } from 'vue'
import type { MemoryEdge } from '@/types/memoryGraph'
import { RELATION_COLORS } from '@/types/memoryGraph'

const props = defineProps<{
  edge: MemoryEdge
  x1: number
  y1: number
  x2: number
  y2: number
  dimmed?: boolean
}>()

/** Stroke color from relation type, fallback to default */
const stroke = computed(() => RELATION_COLORS[props.edge.type] ?? RELATION_COLORS.default)

/** Stroke width mapped from weight (0-1) → 1-4px */
const strokeWidth = computed(() => 1 + props.edge.weight * 3)
</script>

<template>
  <line
    class="graph-edge"
    :class="{ dimmed }"
    :x1="x1"
    :y1="y1"
    :x2="x2"
    :y2="y2"
    :stroke="stroke"
    :stroke-width="strokeWidth"
    opacity="0.4"
    stroke-linecap="round"
  >
    <title>{{ edge.label }}</title>
  </line>
</template>
