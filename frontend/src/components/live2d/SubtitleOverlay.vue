<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useSubtitle } from '@/composables/useSubtitle'
import { useSubtitleStore } from '@/stores/subtitle'

const { store, text, translation, visible, isStreaming } = useSubtitle()

const subStore = useSubtitleStore()

const showOriginal = computed(
  () => store.displayMode === 'original' || store.displayMode === 'bilingual',
)

const showTranslation = computed(
  () =>
    (store.displayMode === 'translated' || store.displayMode === 'bilingual') && translation.value,
)

// ===== Responsive container tracking (ResizeObserver) =====
const containerWidth = ref(0)
const containerHeight = ref(0)
const panelWidth = ref(0) // InteractivePanel rendered width, 0 if hidden/collapsed
const panelRef = ref<HTMLDivElement | null>(null)
let containerObserver: ResizeObserver | null = null
let panelObserver: ResizeObserver | null = null

// ===== Position calculation (ratio-based) =====

const hasCustomPosition = computed(
  () =>
    store.posX != null &&
    store.posY != null &&
    typeof store.posX === 'number' &&
    typeof store.posY === 'number',
)

/** Clamp ratio to keep panel mostly visible */
const CLAMP_X_MIN = 0.05
const CLAMP_X_MAX = 0.95
const CLAMP_Y_MIN = 0.02
const CLAMP_Y_MAX = 0.98

const positionStyle = computed(() => {
  if (hasCustomPosition.value && containerWidth.value > 0) {
    // Custom position: ratio-based via JS (needs ResizeObserver container dimensions)
    return {
      left: `${store.posX! * containerWidth.value}px`,
      bottom: `${store.posY! * containerHeight.value}px`,
      transform: 'translateX(-50%)',
      maxWidth: '80vw',
    }
  }
  // Default centered. The earlier `calc(50% - 200px)` was a stale hardcoded
  // offset that shifted the subtitle ~200px left of the container center
  // (verified via Playwright: container center=605px, subtitle center=405px).
  // 50% + translateX(-50%) centers it on the Live2D model, matching the
  // custom-position branch with posX=0.5.
  return {
    left: `50%`,
    transform: 'translateX(-50%)',
    maxWidth: '80vw',
  }
})

// ===== Drag support (ratio-based) =====
const isDragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const dragOriginRatioX = ref(0)
const dragOriginRatioY = ref(0)

function onDragStart(e: MouseEvent): void {
  // Only left-click
  if (e.button !== 0) return
  isDragging.value = true
  dragStartX.value = e.clientX
  dragStartY.value = e.clientY

  // Get current position as ratios
  if (hasCustomPosition.value) {
    dragOriginRatioX.value = store.posX!
    dragOriginRatioY.value = store.posY!
  } else if (panelRef.value && containerWidth.value > 0) {
    // Compute current ratio from DOM (default centered position)
    const rect = panelRef.value.getBoundingClientRect()
    const parentRect = panelRef.value.offsetParent?.getBoundingClientRect()
    if (parentRect) {
      // Panel center X to ratio
      const centerX = rect.left + rect.width / 2
      dragOriginRatioX.value = centerX / containerWidth.value
      // Panel bottom to ratio
      dragOriginRatioY.value = (parentRect.bottom - rect.bottom) / containerHeight.value
    }
  }

  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
}

function onDragMove(e: MouseEvent): void {
  if (!isDragging.value || containerWidth.value <= 0) return
  const dx = e.clientX - dragStartX.value
  const dy = e.clientY - dragStartY.value

  // Convert pixel delta to ratio delta
  const ratioDx = dx / containerWidth.value
  const ratioDy = -dy / containerHeight.value // inverted: bottom Y

  let newXRatio = dragOriginRatioX.value + ratioDx
  let newYRatio = dragOriginRatioY.value + ratioDy

  // Clamp to keep panel mostly visible
  newXRatio = Math.min(CLAMP_X_MAX, Math.max(CLAMP_X_MIN, newXRatio))
  newYRatio = Math.min(CLAMP_Y_MAX, Math.max(CLAMP_Y_MIN, newYRatio))

  subStore.setPosition(newXRatio, newYRatio)
}

function onDragEnd(): void {
  isDragging.value = false
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
}

// ===== ResizeObserver lifecycle =====

function setupResizeObservers(): void {
  // Observe Live2D container (always present)
  if (!containerObserver) {
    const container = document.querySelector('.live2d-container') as HTMLElement | null
    if (container) {
      containerObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const { width, height } = entry.contentRect
          if (width > 0 && height > 0) {
            containerWidth.value = width
            containerHeight.value = height
          }
        }
      })
      containerObserver.observe(container)
    }
  }

  // Observe InteractivePanel width (may appear/disappear via collapse/popout)
  if (!panelObserver) {
    const panel = document.querySelector('.interactive-panel') as HTMLElement | null
    if (panel) {
      panelObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          panelWidth.value = entry.contentRect.width
        }
      })
      panelObserver.observe(panel)
    }
  }
}

onMounted(() => {
  setupResizeObservers()
})

// Retry panel observation when subtitle becomes visible (panel may not exist yet)
watch([visible, () => store.enabled], async ([vis, ena]) => {
  if (vis && ena) {
    await nextTick()
    setupResizeObservers()
  }
})

onUnmounted(() => {
  if (containerObserver) {
    containerObserver.disconnect()
    containerObserver = null
  }
  if (panelObserver) {
    panelObserver.disconnect()
    panelObserver = null
  }
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
})
</script>

<template>
  <Transition name="subtitle">
    <div
      v-if="visible && text && store.enabled"
      class="absolute z-40"
      :class="!hasCustomPosition ? 'bottom-4' : ''"
      :style="positionStyle"
    >
      <div
        ref="panelRef"
        class="bg-c-bg/70 backdrop-blur-[20px] border border-c-border rounded-xl px-6 py-[14px] max-w-[560px] flex flex-col items-center gap-1.5 select-none"
        :class="[isDragging ? 'cursor-grabbing' : 'cursor-grab', 'pointer-events-auto']"
        @mousedown.prevent="onDragStart"
      >
        <!-- Drag handle (decorative dots + visual indicator) -->
        <div class="flex items-center gap-2 mb-1 opacity-60">
          <span class="w-2 h-2 rounded-full bg-c-accent/60" />
          <span class="w-2 h-2 rounded-full bg-c-blue/50" />
          <span class="w-2 h-2 rounded-full bg-c-accent/60" />
          <span class="text-10px text-c-text-muted ml-1">↕ 拖拽</span>
        </div>

        <!-- Original text -->
        <p v-if="showOriginal" class="text-lg font-medium text-c-text text-center leading-snug">
          {{ text }}
          <span
            v-if="isStreaming"
            class="inline-block w-2 h-5 bg-c-accent/80 rounded-sm ml-1 animate-blink align-middle"
          />
        </p>

        <!-- Translation text -->
        <p v-if="showTranslation" class="text-xs text-c-accent text-center leading-snug">
          {{ translation }}
        </p>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.subtitle-enter-active {
  animation: popIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.subtitle-leave-active {
  animation: fadeOut 0.3s var(--ease-out-expo);
}

@keyframes popIn {
  0% {
    opacity: 0;
    transform: translateX(-50%) translateY(20px) scale(0.95);
  }
  100% {
    opacity: 1;
    transform: translateX(-50%) translateY(0) scale(1);
  }
}

@keyframes fadeOut {
  0% {
    opacity: 1;
  }
  100% {
    opacity: 0;
  }
}
</style>
