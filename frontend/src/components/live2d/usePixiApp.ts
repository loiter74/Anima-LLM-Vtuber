import { type Ref } from 'vue'
import type { Application } from 'pixi.js'

// ===== PIXI Application State =====

let app: Application | null = null
let container: HTMLElement | null = null
let lastCanvasW = 0
let lastCanvasH = 0

export function getApp(): Application | null {
  return app
}
export function getContainer(): HTMLElement | null {
  return container
}
export function getLastCanvasW(): number {
  return lastCanvasW
}
export function getLastCanvasH(): number {
  return lastCanvasH
}

// ===== PIXI Application Initialization =====

export async function initPixiApp(canvasRef: Ref<HTMLCanvasElement | null>): Promise<void> {
  console.log('[PixiApp] initPixiApp called, canvasRef.value:', canvasRef.value)
  if (!canvasRef.value) {
    console.error('[PixiApp] Canvas ref is null, cannot initialize')
    return
  }
  container = canvasRef.value.parentElement
  console.log('[PixiApp] Container:', container)

  const PIXI = await import('pixi.js')

  // Required: pixi-live2d-display references window.PIXI.Ticker internally
  window.PIXI = PIXI

  app = new PIXI.Application({
    view: canvasRef.value,
    width: container?.clientWidth || 400,
    height: container?.clientHeight || 600,
    transparent: true,
    autoDensity: true,
    resolution: window.devicePixelRatio || 1,
    antialias: true,
    backgroundAlpha: 0,
    preserveDrawingBuffer: true,
  })

  lastCanvasW = app.screen.width
  lastCanvasH = app.screen.height
}

// ===== Resize =====

/**
 * Resize the PIXI renderer to match the current container size.
 * Returns the old dimensions so the caller can adjust model position proportionally.
 */
export function handlePixiResize(): { oldW: number; oldH: number } | null {
  if (!app || !container) return null
  const oldW = lastCanvasW || app.screen.width
  const oldH = lastCanvasH || app.screen.height
  app.renderer.resize(container.clientWidth, container.clientHeight)
  lastCanvasW = app.screen.width
  lastCanvasH = app.screen.height
  return { oldW, oldH }
}

// ===== Cleanup =====

export function destroyPixiApp(): void {
  if (app) {
    app.destroy(true)
    app = null
  }
  container = null
}
