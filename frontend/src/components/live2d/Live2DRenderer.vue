<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useLive2D } from './useLive2D'
import { MODEL_PATH } from './useLive2D'
import SubtitleOverlay from './SubtitleOverlay.vue'
import { useMobile } from '@/composables/useMobile'

const { isMobile } = useMobile()
const containerRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const live2d = useLive2D(canvasRef)

// Mobile: toggle to disable Live2D for performance
const live2dEnabled = ref(!isMobile.value)  // Disable on mobile by default to avoid WebGL issues

onMounted(async () => {
  await live2d.init()

  // Expose resetView globally for SettingsPanel button
  ;(window as any).__live2dResetView = () => live2d.resetView()

  // Load default model; user can load others via external API
  try {
    await live2d.loadModel(MODEL_PATH)
  } catch {
    // Model not found is OK, user can load one later
  }
})

function handleMouseDown(e: MouseEvent): void {
  live2d.startDrag(e.clientX, e.clientY)
}

function handleMouseMove(e: MouseEvent): void {
  if (live2d.isDragging.value) {
    live2d.onDrag(e.clientX, e.clientY)
    return
  }
  // Eye/head tracking when not dragging
  if (!live2d.isLoaded.value || !containerRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  live2d.focus(e.clientX - rect.left, e.clientY - rect.top)
}

function handleMouseUp(): void {
  live2d.stopDrag()
}

function handleMouseLeave(): void {
  live2d.stopDrag()
  live2d.focus(0, 0)
}

function handleWheel(e: WheelEvent): void {
  e.preventDefault()
  const sensitivity = 0.0015
  const delta = -e.deltaY * sensitivity
  live2d.zoom(delta)
}

// Mobile: touch drag support
let touchStartX = 0
let touchStartY = 0

function handleTouchStart(e: TouchEvent): void {
  if (e.touches.length === 1) {
    touchStartX = e.touches[0].clientX
    touchStartY = e.touches[0].clientY
    live2d.startDrag(touchStartX, touchStartY)
  }
}

function handleTouchMove(e: TouchEvent): void {
  if (e.touches.length === 1 && live2d.isDragging.value) {
    live2d.onDrag(e.touches[0].clientX, e.touches[0].clientY)
  }
}

function handleTouchEnd(): void {
  live2d.stopDrag()
}

function toggleLive2D(): void {
  live2dEnabled.value = !live2dEnabled.value
}
</script>

<template>
  <div
    ref="containerRef"
    class="relative w-full h-full select-none live2d-container"
    :style="isMobile ? { touchAction: 'none' } : {}"
    @mousedown="handleMouseDown"
    @mousemove="handleMouseMove"
    @mouseup="handleMouseUp"
    @mouseleave="handleMouseLeave"
    @wheel="handleWheel"
    @touchstart.passive="handleTouchStart"
    @touchmove.passive="handleTouchMove"
    @touchend.passive="handleTouchEnd"
  >
    <!-- Mobile: toggle button to enable/disable Live2D -->
    <button
      v-if="isMobile"
      class="absolute top-2 right-2 z-50 px-2 py-1 rounded-lg bg-c-bg/60 backdrop-blur-sm text-10px border border-c-border/30 transition-colors"
      :class="live2dEnabled ? 'text-c-accent' : 'text-c-text-dim'"
      @click.stop="toggleLive2D"
    >
      {{ live2dEnabled ? '🎭 Live2D ON' : '🎭 Live2D OFF' }}
    </button>

    <!-- Show canvas when Live2D is enabled (model may still be loading) -->
    <canvas v-if="live2dEnabled" ref="canvasRef" class="w-full h-full" />

    <!-- Mobile: static placeholder when Live2D disabled -->
    <div
      v-if="isMobile && !live2dEnabled"
      class="absolute inset-0 flex items-center justify-center"
    >
      <div class="text-center text-c-text-muted">
        <p class="text-4xl mb-2">🎭</p>
        <p class="text-xs opacity-60">Live2D 已暂停（节省性能）</p>
      </div>
    </div>

    <!-- Dragging indicator -->
    <div
      v-if="live2d.isDragging.value"
      class="absolute top-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-c-bg/60 backdrop-blur-sm text-xs text-c-text-dim pointer-events-none"
    >
      拖拽移动中
    </div>

    <!-- HUD: zoom & position info + reset button (only when model loaded, desktop only) -->
    <div
      v-if="live2d.modelInfo.value && !isMobile"
      class="absolute bottom-2 right-2 flex items-center gap-1"
    >
      <button
        class="px-2 py-1 rounded bg-c-bg/50 backdrop-blur-sm text-10px text-c-text-muted hover:text-c-accent hover:bg-c-bg/80 transition-colors pointer-events-auto"
        title="复位位置和缩放"
        aria-label="复位 Live2D 位置和缩放"
      @click.stop="live2d.resetView()"
      >
        ↺ 复位
      </button>
      <div class="px-2 py-1 rounded bg-c-bg/50 backdrop-blur-sm text-10px text-c-text-muted pointer-events-none leading-tight">
        <div>缩放 {{ live2d.modelInfo.value.userScale }}x</div>
        <div>位置 {{ live2d.modelInfo.value.position }}</div>
      </div>
    </div>

    <!-- Loading state -->
    <div
      v-if="live2d.isLoading.value && live2dEnabled"
      class="absolute inset-0 flex items-center justify-center pointer-events-none"
    >
      <div class="glass px-6 py-3 text-sm text-c-text-dim flex items-center gap-2">
        <span class="animate-pulse">加载 Live2D 模型中...</span>
      </div>
    </div>

    <!-- Error state with retry button -->
    <div
      v-if="live2d.loadError.value"
      class="absolute inset-0 flex items-center justify-center"
    >
      <div class="glass px-6 py-4 text-sm text-center">
        <p class="text-c-error mb-3">模型加载失败</p>
        <p class="text-c-text-dim text-xs mb-4 max-w-[240px]">{{ live2d.loadError.value }}</p>
        <button
          class="px-4 py-1.5 rounded-lg bg-c-accent/20 text-c-accent text-xs hover:bg-c-accent/30 transition-colors pointer-events-auto"
          @click.stop="live2d.retryLoad()"
        >
          ↻ 重试加载
        </button>
      </div>
    </div>

    <!-- Idle state (no model) -->
    <div
      v-if="!live2d.isLoaded.value && !live2d.isLoading.value && !live2d.loadError.value && live2dEnabled"
      class="absolute inset-0 flex items-center justify-center pointer-events-none"
    >
      <div class="text-center text-c-text-muted">
        <p class="text-2xl mb-2">🎭</p>
        <p class="text-sm">未加载 Live2D 模型</p>
      </div>
    </div>

    <!-- Subtitle overlay -->
    <SubtitleOverlay />
  </div>
</template>
