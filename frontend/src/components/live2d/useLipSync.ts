import { getModel } from './useLive2DModel'

// ===== Mouth Parameter Candidates (Cubism 3/4) =====

export const MOUTH_PARAMS = ['ParamMouthOpenY', 'ParamMouthOpen', 'PARAM_MOUTH_OPEN']

// ===== LipSync State =====

let mouthValue = 0
let targetMouth = 0
let mouthParam: string | null = null
let lipSyncCancel: (() => void) | null = null
let _lipSyncRafActive = false // when true, PIXI ticker lip sync is disabled

export function getIsLipSyncRafActive(): boolean {
  return _lipSyncRafActive
}

// ===== Mouth Target =====

export function setMouthTarget(value: number): void {
  targetMouth = Math.max(0, Math.min(1, value))
}

// ===== PIXI Ticker LipSync =====

export function tickLipSync(): void {
  // RAF-based lip sync takes priority over PIXI ticker
  if (_lipSyncRafActive) return
  const model = getModel()
  if (!model) return

  const delta = Math.abs(targetMouth - mouthValue)
  const factor = 0.5 + 0.4 * Math.min(delta / 0.3, 1.0)
  mouthValue += (targetMouth - mouthValue) * factor

  if (!mouthParam) {
    for (const name of MOUTH_PARAMS) {
      const idx = model.internalModel?.coreModel?.getParameterIndex(name)
      if (idx >= 0) {
        mouthParam = name
        break
      }
    }
  }

  if (mouthParam) {
    const idx = model.internalModel.coreModel.getParameterIndex(mouthParam)
    if (idx >= 0) model.internalModel.coreModel.setParameterValueByIndex(idx, mouthValue)
  }
}

// ===== RAF-based LipSync (for audio playback) =====

export function startLipSync(audio: HTMLAudioElement, volumes: number[]): void {
  stopLipSync()
  _lipSyncRafActive = true
  const model = getModel()

  // Stop idle motion that may override mouth parameters via motionManager
  try {
    model?.internalModel?.motionManager?.stopAllMotions()
  } catch {}
  const intervalMs = 20
  let lastIndex = -1
  let hasStarted = false
  let preRollCount = 0
  const preRollTarget = 3
  let lipSyncMouth = 0
  let lipSyncTarget = 0

  // Direct parameter setter — runs every RAF frame, NOT through the PIXI
  // ticker, so it wins over any motion-driven mouth keyframes.
  function setLipSyncParam(value: number) {
    lipSyncTarget = Math.max(0, Math.min(1, value))
    // Smooth interpolation
    const delta = Math.abs(lipSyncTarget - lipSyncMouth)
    const factor = 0.5 + 0.4 * Math.min(delta / 0.3, 1.0)
    lipSyncMouth += (lipSyncTarget - lipSyncMouth) * factor
    const m = getModel()
    if (!mouthParam) {
      for (const name of MOUTH_PARAMS) {
        const idx = m?.internalModel?.coreModel?.getParameterIndex(name)
        if (idx !== undefined && idx >= 0) {
          mouthParam = name
          break
        }
      }
    }
    if (mouthParam && m?.internalModel?.coreModel) {
      const idx = m.internalModel.coreModel.getParameterIndex(mouthParam)
      if (idx >= 0) m.internalModel.coreModel.setParameterValueByIndex(idx, lipSyncMouth)
    }
  }

  const tick = () => {
    if (audio.ended || (hasStarted && audio.paused)) {
      setLipSyncParam(0)
      return
    }

    if (!hasStarted) {
      if (audio.paused) {
        if (preRollCount < preRollTarget && preRollCount < volumes.length) {
          setLipSyncParam(volumes[preRollCount])
          preRollCount++
        }
        requestAnimationFrame(tick)
        return
      }
      hasStarted = true
    }

    const rawIndex = Math.floor((audio.currentTime * 1000) / intervalMs)
    const index = rawIndex + preRollCount
    if (index !== lastIndex) {
      setLipSyncParam(index < volumes.length ? volumes[index] : 0)
      lastIndex = index
    } else {
      // Keep smoothing toward current target even on same index
      setLipSyncParam(lipSyncTarget)
    }
    requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)

  lipSyncCancel = () => {
    _lipSyncRafActive = false
    setLipSyncParam(0)
  }
}

export function stopLipSync(): void {
  lipSyncCancel?.()
  lipSyncCancel = null
  _lipSyncRafActive = false
  setMouthTarget(0)
  const model = getModel()
  // Restart idle motion for head sway now that lip sync is done
  try {
    model?.motion?.('Idle', 0)
  } catch {}
}

// ===== State Reset (for destroy) =====

export function resetLipSyncState(): void {
  mouthValue = 0
  targetMouth = 0
  mouthParam = null
  lipSyncCancel = null
  _lipSyncRafActive = false
}
