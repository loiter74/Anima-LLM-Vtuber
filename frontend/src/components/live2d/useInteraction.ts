import { ref } from 'vue'
import { getApp } from './usePixiApp'
import {
  getModel, applyScale, centerModel,
  getUserScale, setUserScale, getStrategy,
  STRATEGIES, setStrategy,
  POS_X_RATIO, POS_Y_RATIO, INITIAL_SCALE,
  FIXED_X, FIXED_Y, USE_FIXED_POSITION
} from './useLive2DModel'

// ===== Reactive State (exposed to Vue templates) =====

export const isLoaded = ref(false)
export const isLoading = ref(false)
export const loadError = ref('')
export const modelInfo = ref<Record<string, string> | null>(null)
export const isDragging = ref(false)

// ===== Drag State =====

let dragStartX = 0
let dragStartY = 0
let modelStartX = 0
let modelStartY = 0

// ===== Drag =====

export function startDrag(clientX: number, clientY: number): void {
  const model = getModel()
  if (!model) return
  isDragging.value = true
  dragStartX = clientX
  dragStartY = clientY
  modelStartX = model.x
  modelStartY = model.y
}

export function onDrag(clientX: number, clientY: number): void {
  const model = getModel()
  if (!isDragging.value || !model) return
  const dx = clientX - dragStartX
  const dy = clientY - dragStartY
  model.x = modelStartX + dx
  model.y = modelStartY + dy
  updateModelInfo()
}

export function stopDrag(): void {
  if (!isDragging.value) return
  isDragging.value = false
}

// ===== Mouse Focus =====

/** Mouse focus (eye/head tracking) */
export function focus(x: number, y: number): void {
  const model = getModel()
  if (!model) return
  model.focus(x, y)
}

// ===== Zoom =====

/** Scroll-wheel zoom. Positive delta = zoom in, negative = zoom out. Range 0.05x – 10x. */
export function zoom(delta: number): void {
  setUserScale(Math.max(0.05, Math.min(10.0, getUserScale() * Math.exp(delta))))
  applyScale()
  updateModelInfo()
}

// ===== Reset View =====

/** Reset to user's preferred initial position and scale */
export function resetView(): void {
  const app = getApp()
  const model = getModel()
  setUserScale(INITIAL_SCALE)
  applyScale()
  if (model && app) {
    if (USE_FIXED_POSITION) {
      model.x = FIXED_X
      model.y = FIXED_Y
    } else {
      model.x = app.screen.width * POS_X_RATIO
      model.y = app.screen.height * POS_Y_RATIO
    }
  }
  updateModelInfo()
}

// ===== Scale Strategy =====

export function setScaleStrategy(s: string): void {
  if (STRATEGIES[s]) {
    setStrategy(s)
    applyScale()
    updateModelInfo()
  }
}

// ===== Model Info =====

export function updateModelInfo(): void {
  const app = getApp()
  const model = getModel()
  if (!model || !app) { modelInfo.value = null; return }
  modelInfo.value = {
    strategy: getStrategy(),
    userScale: getUserScale().toFixed(2),
    position: `(${model.x.toFixed(0)}, ${model.y.toFixed(0)})`,
    canvas: `${app.screen.width}x${app.screen.height}`
  }
}
