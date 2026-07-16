<script setup lang="ts">
/**
 * MemoryGraph — main canvas that orchestrates the knowledge graph visualization.
 *
 * Uses d3-force for layout, manual zoom/pan/drag (no d3-zoom dependency).
 * SVG-only rendering via Vue template components.
 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from 'd3-force'
import { parseMemoryGraph } from '@/types/memoryGraph'
import type { MemoryNode, MemoryEdge } from '@/types/memoryGraph'
import MemoryGraphControls from './MemoryGraphControls.vue'
import MemoryGraphNode from './MemoryGraphNode.vue'
import MemoryGraphEdge from './MemoryGraphEdge.vue'

// ── Props & Emits ────────────────────────────────────────

interface WikiPage {
  path: string
  title: string
  page_type: string
  content: string
  tags: string[]
  updated_at: string
  salience?: number
  relations?: Array<{
    source_id: string
    target_id: string
    relation_type: string
    metadata?: Record<string, unknown>
  }>
}

const props = defineProps<{
  pages: WikiPage[]
}>()

const emit = defineEmits<{
  'node-click': [node: MemoryNode]
}>()

// ── Refs ─────────────────────────────────────────────────

const svgRef = ref<SVGSVGElement | null>(null)
const simulation = ref<Simulation<MemoryNode, SimulationLinkDatum<MemoryNode>> | null>(null)

const graphNodes = ref<MemoryNode[]>([])
const graphEdges = ref<MemoryEdge[]>([])

// Filter state
const searchQuery = ref('')
const selectedCategory = ref<string | null>(null)

// Zoom/pan state
const zoomTransform = ref({ x: 0, y: 0, k: 1 })
const isPanning = ref(false)
const panStart = ref({ x: 0, y: 0 })

// Node dragging state
const dragNode = ref<MemoryNode | null>(null)
const dragOffset = ref({ x: 0, y: 0 })

// Tooltip state
const tooltip = ref<{ show: boolean; x: number; y: number; text: string }>({
  show: false,
  x: 0,
  y: 0,
  text: '',
})

// ── Computed ─────────────────────────────────────────────

/** Unique categories from current nodes */
const categories = computed(() => {
  const cats = new Set(graphNodes.value.map((n) => n.category))
  return Array.from(cats).sort()
})

/** Node IDs matching search query */
const searchMatchIds = computed(() => {
  if (!searchQuery.value.trim()) return null
  const q = searchQuery.value.toLowerCase()
  return new Set(
    graphNodes.value
      .filter((n) => n.label.toLowerCase().includes(q) || n.category.toLowerCase().includes(q))
      .map((n) => n.id),
  )
})

/** Whether any filter is active */
const hasFilter = computed(() => searchMatchIds.value !== null || selectedCategory.value !== null)

/** Node ID → x,y lookup for edge positioning */
const nodePositions = computed(() => {
  const map = new Map<string, { x: number; y: number }>()
  for (const node of graphNodes.value) {
    map.set(node.id, { x: node.x ?? 0, y: node.y ?? 0 })
  }
  return map
})

/** SVG transform string */
const svgTransform = computed(() => {
  const { x, y, k } = zoomTransform.value
  return `translate(${x}, ${y}) scale(${k})`
})

/** Safely extract node ID from edge source/target (d3-force replaces strings with objects at runtime) */
function edgeNodeId(ref: string | SimulationNodeDatum): string {
  if (typeof ref === 'string') return ref
  // After d3-force tick, source/target are MemoryNode objects with .id
  return (ref as unknown as MemoryNode).id
}

/** Check if a node is dimmed by filters */
function isNodeDimmed(node: MemoryNode): boolean {
  if (searchMatchIds.value !== null && !searchMatchIds.value.has(node.id)) return true
  if (selectedCategory.value !== null && node.category !== selectedCategory.value) return true
  return false
}

/** Check if an edge is dimmed (either endpoint dimmed) */
function isEdgeDimmed(edge: MemoryEdge): boolean {
  if (!hasFilter.value) return false
  const srcId = edgeNodeId(edge.source)
  const tgtId = edgeNodeId(edge.target)
  const srcNode = graphNodes.value.find((n) => n.id === srcId)
  const tgtNode = graphNodes.value.find((n) => n.id === tgtId)
  if (srcNode && isNodeDimmed(srcNode)) return true
  if (tgtNode && isNodeDimmed(tgtNode)) return true
  return false
}

// ── Zoom controls ────────────────────────────────────────

function zoomIn() {
  const { x, y, k } = zoomTransform.value
  const newK = Math.min(k * 1.3, 5)
  // Zoom toward center of SVG
  const svg = svgRef.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const cx = rect.width / 2
  const cy = rect.height / 2
  zoomTransform.value = {
    x: cx - (cx - x) * (newK / k),
    y: cy - (cy - y) * (newK / k),
    k: newK,
  }
}

function zoomOut() {
  const { x, y, k } = zoomTransform.value
  const newK = Math.max(k / 1.3, 0.2)
  const svg = svgRef.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const cx = rect.width / 2
  const cy = rect.height / 2
  zoomTransform.value = {
    x: cx - (cx - x) * (newK / k),
    y: cy - (cy - y) * (newK / k),
    k: newK,
  }
}

function zoomReset() {
  zoomTransform.value = { x: 0, y: 0, k: 1 }
}

// ── Mouse handlers ───────────────────────────────────────

function handleWheel(event: WheelEvent) {
  event.preventDefault()
  const { x, y, k } = zoomTransform.value
  const factor = event.deltaY > 0 ? 0.9 : 1.1
  const newK = Math.max(0.2, Math.min(5, k * factor))

  // Zoom toward mouse position
  const svg = svgRef.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const mx = event.clientX - rect.left
  const my = event.clientY - rect.top

  zoomTransform.value = {
    x: mx - (mx - x) * (newK / k),
    y: my - (my - y) * (newK / k),
    k: newK,
  }
}

function handleSvgMouseDown(event: MouseEvent) {
  // Only start pan if clicking on SVG background (not a node)
  const target = event.target as SVGElement
  if (target.closest('.graph-node')) return

  isPanning.value = true
  panStart.value = {
    x: event.clientX - zoomTransform.value.x,
    y: event.clientY - zoomTransform.value.y,
  }
}

function handleMouseMove(event: MouseEvent) {
  // Node dragging
  if (dragNode.value) {
    const { k, x: zx, y: zy } = zoomTransform.value
    dragNode.value.fx = (event.clientX - zx - dragOffset.value.x) / k
    dragNode.value.fy = (event.clientY - zy - dragOffset.value.y) / k
    return
  }

  // Panning
  if (isPanning.value) {
    zoomTransform.value = {
      ...zoomTransform.value,
      x: event.clientX - panStart.value.x,
      y: event.clientY - panStart.value.y,
    }
  }
}

function handleMouseUp() {
  if (dragNode.value) {
    // Release node from fixed position
    dragNode.value.fx = null
    dragNode.value.fy = null
    dragNode.value = null
    simulation.value?.alpha(0.3).restart()
  }
  isPanning.value = false
}

function handleNodeDragStart(node: MemoryNode, event: MouseEvent) {
  const { k, x: zx, y: zy } = zoomTransform.value
  dragNode.value = node
  dragOffset.value = {
    x: event.clientX - zx - (node.x ?? 0) * k,
    y: event.clientY - zy - (node.y ?? 0) * k,
  }
  // Fix node position during drag
  node.fx = node.x
  node.fy = node.y
  simulation.value?.alphaTarget(0.3).restart()
}

function handleNodeClick(node: MemoryNode) {
  emit('node-click', node)
}

// ── Tooltip ──────────────────────────────────────────────

function showEdgeTooltip(edge: MemoryEdge, event: MouseEvent) {
  tooltip.value = {
    show: true,
    x: event.clientX + 12,
    y: event.clientY - 8,
    text: edge.label,
  }
}

function hideTooltip() {
  tooltip.value.show = false
}

// ── Force simulation ─────────────────────────────────────

function initSimulation() {
  const data = parseMemoryGraph(props.pages)
  graphNodes.value = data.nodes
  graphEdges.value = data.edges

  // Initialize positions near center
  const width = svgRef.value?.clientWidth ?? 800
  const height = svgRef.value?.clientHeight ?? 600

  for (const node of graphNodes.value) {
    node.x = width / 2 + (Math.random() - 0.5) * 200
    node.y = height / 2 + (Math.random() - 0.5) * 200
  }

  // Stop existing simulation
  simulation.value?.stop()

  const sim = forceSimulation<MemoryNode>(graphNodes.value)
    .force(
      'link',
      forceLink<MemoryNode, SimulationLinkDatum<MemoryNode>>(graphEdges.value)
        .id((d) => d.id)
        .distance(120),
    )
    .force('charge', forceManyBody<MemoryNode>().strength(-300))
    .force('center', forceCenter<MemoryNode>(width / 2, height / 2))
    .force(
      'collide',
      forceCollide<MemoryNode>().radius((d) => 8 + d.importance * 24 + 4),
    )
    .alphaDecay(0.02)
    .on('tick', () => {
      // Trigger Vue reactivity by creating new array reference
      graphNodes.value = [...graphNodes.value]
    })

  simulation.value = sim
}

function stopSimulation() {
  simulation.value?.stop()
  simulation.value = null
}

// ── Lifecycle ────────────────────────────────────────────

onMounted(() => {
  nextTick(() => {
    if (props.pages.length > 0) {
      initSimulation()
    }
  })

  // Global mouse events for drag/pan
  window.addEventListener('mousemove', handleMouseMove)
  window.addEventListener('mouseup', handleMouseUp)
})

onBeforeUnmount(() => {
  stopSimulation()
  window.removeEventListener('mousemove', handleMouseMove)
  window.removeEventListener('mouseup', handleMouseUp)
})

// Re-run simulation when pages data changes
watch(
  () => props.pages,
  (newPages) => {
    if (newPages.length > 0) {
      initSimulation()
    } else {
      stopSimulation()
      graphNodes.value = []
      graphEdges.value = []
    }
  },
  { deep: true },
)
</script>

<template>
  <div class="graph-container">
    <!-- Controls toolbar -->
    <MemoryGraphControls
      v-model:search-query="searchQuery"
      v-model:selected-category="selectedCategory"
      :categories="categories"
      @zoom-in="zoomIn"
      @zoom-out="zoomOut"
      @zoom-reset="zoomReset"
    />

    <!-- Empty state -->
    <div v-if="pages.length === 0" class="graph-empty">
      <span class="graph-empty-icon">🧠</span>
      <span>No memory data available</span>
    </div>

    <!-- Graph SVG -->
    <svg
      v-else
      ref="svgRef"
      class="w-full h-full"
      @wheel.prevent="handleWheel"
      @mousedown="handleSvgMouseDown"
    >
      <g :transform="svgTransform">
        <!-- Edges (render first, behind nodes) -->
        <MemoryGraphEdge
          v-for="(edge, i) in graphEdges"
          :key="`edge-${i}`"
          :edge="edge"
          :x1="nodePositions.get(edgeNodeId(edge.source))?.x ?? 0"
          :y1="nodePositions.get(edgeNodeId(edge.source))?.y ?? 0"
          :x2="nodePositions.get(edgeNodeId(edge.target))?.x ?? 0"
          :y2="nodePositions.get(edgeNodeId(edge.target))?.y ?? 0"
          :dimmed="isEdgeDimmed(edge)"
          @mouseenter="showEdgeTooltip(edge, $event)"
          @mouseleave="hideTooltip"
        />

        <!-- Nodes -->
        <MemoryGraphNode
          v-for="node in graphNodes"
          :key="node.id"
          :node="node"
          :dimmed="isNodeDimmed(node)"
          :selected="false"
          @click="handleNodeClick"
          @drag-start="handleNodeDragStart"
        />
      </g>
    </svg>

    <!-- Tooltip -->
    <Teleport to="body">
      <div
        v-if="tooltip.show"
        class="graph-tooltip"
        :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
      >
        {{ tooltip.text }}
      </div>
    </Teleport>
  </div>
</template>

<style>
@import '@/styles/graph.css';
</style>
