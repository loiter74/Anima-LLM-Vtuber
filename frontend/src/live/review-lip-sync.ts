import {
  resolveMouthParameterIndex,
  type MouthParameterLookup,
} from '@/components/live2d/mouthParameter'

const FRAME_INTERVAL_SECONDS = 0.02
const REVIEW_MOUTH_LEAD_SECONDS = 0.06
const REVIEW_MOUTH_VISIBILITY_EXPONENT = 0.65
const MAX_TIMELINE_FRAMES = 3_000

interface ReviewInternalModel {
  coreModel: MouthParameterLookup & {
    setParameterValueByIndex(index: number, value: number): void
  }
  on(event: 'beforeModelUpdate', listener: () => void): void
  off(event: 'beforeModelUpdate', listener: () => void): void
}

export function bindReviewMouthAfterMotion(
  internalModel: ReviewInternalModel,
  onApplied?: () => void,
): {
  setMouth(value: number): void
  setBeforeApply(callback: (() => void) | null): void
  dispose(): void
} {
  const parameterIndex = resolveMouthParameterIndex(internalModel.coreModel)
  let mouth = 0
  let beforeApply: (() => void) | null = null

  const applyBeforeModelCommit = (): void => {
    beforeApply?.()
    if (parameterIndex >= 0) {
      internalModel.coreModel.setParameterValueByIndex(parameterIndex, mouth)
      if (mouth > 0.02) onApplied?.()
    }
  }
  internalModel.on('beforeModelUpdate', applyBeforeModelCommit)

  return {
    setMouth(value: number): void {
      mouth = Math.max(0, Math.min(1, value))
    },
    setBeforeApply(callback: (() => void) | null): void {
      beforeApply = callback
    },
    dispose(): void {
      beforeApply = null
      internalModel.off('beforeModelUpdate', applyBeforeModelCommit)
      if (parameterIndex >= 0) {
        internalModel.coreModel.setParameterValueByIndex(parameterIndex, 0)
      }
    },
  }
}

export function parseReviewMouthTimeline(raw: string | null): number[] {
  let value: unknown
  try {
    value = JSON.parse(raw ?? '')
  } catch {
    throw new Error('Invalid review mouth timeline')
  }
  if (
    !Array.isArray(value) ||
    value.length === 0 ||
    value.length > MAX_TIMELINE_FRAMES ||
    !value.every((volume) => Number.isFinite(volume) && volume >= 0 && volume <= 1)
  ) {
    throw new Error('Invalid review mouth timeline')
  }
  return value as number[]
}

interface ReviewVolumeTimelineLipSyncOptions {
  audio: HTMLAudioElement
  volumes: readonly number[]
  setMouth(value: number): void
  onObserved?(): void
  requestFrame?: typeof requestAnimationFrame
  cancelFrame?: typeof cancelAnimationFrame
  manualSampling?: boolean
}

export function createReviewVolumeTimelineLipSync(options: ReviewVolumeTimelineLipSyncOptions): {
  start(): void
  sample(): void
  stop(): void
} {
  const requestFrame = options.requestFrame ?? requestAnimationFrame
  const cancelFrame = options.cancelFrame ?? cancelAnimationFrame
  let active = false
  let frameId: number | null = null
  let mouth = 0
  let observed = false

  const writeMouth = (target: number): void => {
    const bounded = Math.max(0, Math.min(1, target))
    const visible = bounded === 0 ? 0 : Math.pow(bounded, REVIEW_MOUTH_VISIBILITY_EXPONENT)
    const delta = Math.abs(visible - mouth)
    const factor = 0.5 + 0.4 * Math.min(delta / 0.3, 1)
    mouth += (visible - mouth) * factor
    options.setMouth(mouth)
    if (!observed && bounded > 0.02) {
      observed = true
      options.onObserved?.()
    }
  }

  const sample = (): void => {
    if (!active) return
    if (options.audio.ended) {
      active = false
      frameId = null
      options.setMouth(0)
      return
    }
    const framePosition =
      (options.audio.currentTime + REVIEW_MOUTH_LEAD_SECONDS) / FRAME_INTERVAL_SECONDS
    const frameIndex = Math.floor(framePosition)
    const frameProgress = framePosition - frameIndex
    const currentVolume = options.volumes[frameIndex] ?? 0
    const nextVolume = options.volumes[frameIndex + 1] ?? 0
    const interpolatedVolume = currentVolume + (nextVolume - currentVolume) * frameProgress
    writeMouth(options.audio.paused ? 0 : interpolatedVolume)
  }

  const tick = (): void => {
    sample()
    if (!active) return
    frameId = requestFrame(tick)
  }

  return {
    start(): void {
      if (active) return
      active = true
      if (!options.manualSampling) tick()
    },
    sample,
    stop(): void {
      active = false
      if (frameId !== null) cancelFrame(frameId)
      frameId = null
      mouth = 0
      options.setMouth(0)
    },
  }
}
