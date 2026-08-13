import { getModel } from './useLive2DModel'
import { resolveMouthParameterIndex, type MouthParameterLookup } from './mouthParameter'
import { createMouthEnvelope } from './mouthEnvelope'

// ===== LipSync State =====

let mouthValue = 0
let targetMouth = 0
let mouthModel: MouthParameterLookup | null = null
let mouthParameterIndex = -1
let lipSyncCancel: (() => void) | null = null
let _lipSyncRafActive = false // when true, PIXI ticker lip sync is disabled

export type MouthTarget = (value: number) => void

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
  const coreModel = model.internalModel?.coreModel
  if (!coreModel) return

  const delta = Math.abs(targetMouth - mouthValue)
  const factor = 0.5 + 0.4 * Math.min(delta / 0.3, 1.0)
  mouthValue += (targetMouth - mouthValue) * factor

  if (coreModel !== mouthModel) {
    mouthModel = coreModel
    mouthParameterIndex = resolveMouthParameterIndex(coreModel)
  }

  if (mouthParameterIndex >= 0) {
    coreModel.setParameterValueByIndex(mouthParameterIndex, mouthValue)
  }
}

// ===== RAF-based LipSync (for audio playback) =====

export function startLipSync(
  audio: HTMLAudioElement,
  volumes: number[],
  setTarget: MouthTarget = setMouthTarget,
): void {
  stopLipSync()
  _lipSyncRafActive = false
  const intervalMs = 20
  let lastIndex = -1
  let hasStarted = false
  let preRollCount = 0
  const preRollTarget = 3
  let lipSyncTarget = 0
  const mouthEnvelope = createMouthEnvelope()

  // RAF tracks the audio envelope only. The PIXI late-frame ticker owns the
  // actual parameter write so mouth opening is always applied after motion
  // and semantic expression overlays.
  function setLipSyncParam(value: number) {
    lipSyncTarget = value === 0 ? mouthEnvelope.reset() : mouthEnvelope.next(value)
    setTarget(lipSyncTarget)
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
  const cancel = lipSyncCancel
  lipSyncCancel = null
  _lipSyncRafActive = false
  if (cancel) cancel()
  else setMouthTarget(0)
}
