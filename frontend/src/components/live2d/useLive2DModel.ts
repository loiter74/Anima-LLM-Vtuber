import type { Cubism4InternalModel, Live2DModel } from 'pixi-live2d-display/cubism4'
import { getApp } from './usePixiApp'
import { isLoaded, isLoading, loadError, updateModelInfo } from './useInteraction'

// ===== Model Configuration (edit these to change model) =====

export const MODEL_PATH = 'live2d/hiyori/Hiyori.model3.json'
// Position is computed as a fraction of canvas dimensions at load time,
// so the model appears at the same relative position on any screen size.
const POS_X_RATIO = 0.741 // 800/1080 = 0.741 (74.1% from left)
const POS_Y_RATIO = 0.677 // 1300/1920 = 0.677 (67.7% from top)
const INITIAL_SCALE = 2.59

// Fixed pixel position (overrides ratio when set)
const FIXED_X = 800
const FIXED_Y = 1300
const USE_FIXED_POSITION = true // Set to false to use ratio-based positioning

export { POS_X_RATIO, POS_Y_RATIO, INITIAL_SCALE, FIXED_X, FIXED_Y, USE_FIXED_POSITION }

export interface ScaleStrategy {
  anchor: [number, number]
  yRatio: number
}

export const STRATEGIES: Record<string, ScaleStrategy> = {
  fit: { anchor: [0.5, 0.5], yRatio: 0.5 },
  contain: { anchor: [0.5, 1.0], yRatio: 1.0 },
  cover: { anchor: [0.5, 0.5], yRatio: 0.5 },
}

// ===== Model State =====

let model: Live2DModel<Cubism4InternalModel> | null = null
let baseBounds: { width: number; height: number } | null = null
let userScale = 1.5
let strategy = 'fit'

export function getModel(): Live2DModel<Cubism4InternalModel> | null {
  return model
}
export function getUserScale(): number {
  return userScale
}
export function getStrategy(): string {
  return strategy
}
export function setUserScale(s: number): void {
  userScale = s
}
export function setStrategy(s: string): void {
  if (STRATEGIES[s]) strategy = s
}

// ===== Model Loading =====

export function unloadModel(): void {
  const app = getApp()
  if (model) {
    app?.stage.removeChild(model)
    model.destroy()
    model = null
    isLoaded.value = false
  }
}

export async function loadModel(modelPath: string): Promise<void> {
  const app = getApp()
  if (!app) {
    loadError.value = 'PixiJS 未初始化，请刷新页面重试'
    isLoading.value = false
    return
  }
  isLoading.value = true
  loadError.value = ''

  // 30-second timeout for the entire loading process
  const LOAD_TIMEOUT_MS = 30_000

  try {
    unloadModel()

    // Dynamic import: Live2D is optional, app works without it
    const { Live2DModel } = await import('pixi-live2d-display/cubism4')

    // Wrap model creation with timeout
    model = (await Promise.race([
      Live2DModel.from(modelPath),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('模型加载超时（30秒）')), LOAD_TIMEOUT_MS),
      ),
    ])) as Live2DModel<Cubism4InternalModel>

    // The manifest exposes only Hiyori_m01 in Idle, so the model's normal
    // idle scheduler can safely keep the gentle sway running without chance.
    try {
      model.internalModel?.motionManager?.stopAllMotions()
    } catch {}
    // Start the calm motion immediately; the one-item Idle group repeats it.
    try {
      model.motion('Idle', 0)
    } catch {}
    model.anchor.set(0.5, 0.5)
    // Will be overridden after applyScale below to user's preferred position
    model.interactive = true

    app.stage.addChild(model)
    const loadedModel = model

    // Wait for bounds to be available (with timeout to prevent infinite loop)
    await Promise.race([
      new Promise<void>((resolve) => {
        const check = () => {
          const b = loadedModel.getBounds()
          if (b?.width > 0) return resolve()
          requestAnimationFrame(check)
        }
        check()
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('模型边界计算超时')), 10_000),
      ),
    ])

    // Cache initial bounds (before any scaling) as the stable reference
    const initialBounds = loadedModel.getBounds()
    baseBounds = { width: initialBounds.width, height: initialBounds.height }

    applyScale()
    // Position model: fixed pixel position or ratio-based
    if (USE_FIXED_POSITION) {
      model.x = FIXED_X
      model.y = FIXED_Y
    } else {
      model.x = app.screen.width * POS_X_RATIO
      model.y = app.screen.height * POS_Y_RATIO
    }
    userScale = INITIAL_SCALE
    applyScale()
    isLoaded.value = true
    isLoading.value = false
    updateModelInfo()
  } catch (err: unknown) {
    loadError.value = err instanceof Error ? err.message : '模型加载失败'
    isLoading.value = false
  }
}

// ===== Scale =====

/**
 * Apply current scale (strategy × userScale) using cached baseBounds.
 * NEVER use real-time getBounds() here — creates a feedback loop.
 */
export function applyScale(): void {
  const app = getApp()
  if (!model || !app || !baseBounds) return
  const canvas = { width: app.screen.width, height: app.screen.height }
  // Use cached initial bounds as stable reference — NEVER real-time getBounds()
  // because getBounds() changes as scale changes, creating a feedback loop.
  const b = baseBounds

  const scales: Record<string, number> = {
    fit: Math.min(canvas.width / b.width, canvas.height / b.height),
    contain: canvas.height / b.height,
    cover: Math.max(canvas.width / b.width, canvas.height / b.height),
  }

  model.scale.set((scales[strategy] || scales.fit) * userScale)
  // NOTE: Do NOT reset model.x/model.y/anchor here — position is
  // managed by drag interaction. Only centerModel() changes position.
}

// ===== Positioning =====

/** Center model in the current canvas. Preserves userScale. */
export function centerModel(): void {
  const app = getApp()
  if (!model || !app) return
  if (USE_FIXED_POSITION) {
    model.x = FIXED_X
    model.y = FIXED_Y
  } else {
    model.x = app.screen.width * POS_X_RATIO
    model.y = app.screen.height * POS_Y_RATIO
  }
  updateModelInfo()
}

// ===== Expression & Motion =====

export function setExpression(name: string): void {
  if (!model) return
  const manager = model.internalModel.motionManager as typeof model.internalModel.motionManager & {
    expressionNames?: string[]
  }
  if (!manager.expressionNames) return
  const idx = manager.expressionNames.indexOf(name)
  if (idx >= 0) model.expression(idx)
}

export function playMotion(group: string, index: number): void {
  model?.motion?.(group, index)
}

export function setClampedParameter(name: string, value: number): void {
  const coreModel = model?.internalModel?.coreModel
  if (!coreModel) return
  const index = coreModel.getParameterIndex(name)
  if (index < 0) return
  const bounded = coreModel as typeof coreModel & {
    getParameterMinimumValue?: (parameterIndex: number) => number
    getParameterMaximumValue?: (parameterIndex: number) => number
  }
  const minimum = bounded.getParameterMinimumValue?.(index) ?? -1
  const maximum = bounded.getParameterMaximumValue?.(index) ?? 1
  coreModel.setParameterValueByIndex(index, Math.max(minimum, Math.min(maximum, value)))
}

export function getParameterValue(name: string): number {
  const coreModel = model?.internalModel?.coreModel
  if (!coreModel) return 0
  const index = coreModel.getParameterIndex(name)
  return index < 0 ? 0 : coreModel.getParameterValueByIndex(index)
}

// ===== Retry =====

/** Retry loading the default model after a failure */
export async function retryLoad(): Promise<void> {
  loadError.value = ''
  isLoaded.value = false
  await loadModel(MODEL_PATH)
}
