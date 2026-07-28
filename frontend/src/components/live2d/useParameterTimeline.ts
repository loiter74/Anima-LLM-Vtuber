import type { ParameterTimeline, ParameterTimelineFrame } from '@/types/socket-events'
import { getModel } from './useLive2DModel'
import {
  playAudio,
  type AudioPlaybackLifecycle,
  type AudioPlaybackPayload,
} from './useAudioPlayback'

// ===== Timeline State =====

let timelinePlaying = false
let timelineFrames: ParameterTimelineFrame[] = []
let timelineDuration = 0
let timelineStart = 0
let timelineFrameIdx = 0
let timelineRaf: number | null = null
const currentParams = new Map<
  string,
  {
    currentValue: number
    targetValue: number
    startTime: number
    duration: number
    startValue: number
  }
>()

// ===== Parameter Setting =====

export function setParam(name: string, value: number): void {
  const model = getModel()
  if (!model?.internalModel?.coreModel) return
  const idx = model.internalModel.coreModel.getParameterIndex(name)
  if (idx >= 0) model.internalModel.coreModel.setParameterValueByIndex(idx, value)
}

// ===== Timeline =====

function tickTimeline(): void {
  if (!timelinePlaying) return
  const currentTime = performance.now() / 1000 - timelineStart

  if (currentTime >= timelineDuration) {
    timelinePlaying = false
    return
  }

  // Process frames
  while (
    timelineFrameIdx < timelineFrames.length &&
    timelineFrames[timelineFrameIdx].timestamp <= currentTime
  ) {
    const frame = timelineFrames[timelineFrameIdx]
    for (const param of frame.parameters) {
      currentParams.set(param.name, {
        targetValue: param.value,
        startTime: currentTime,
        duration: param.duration,
        startValue: currentParams.get(param.name)?.currentValue ?? param.value,
        currentValue: currentParams.get(param.name)?.currentValue ?? param.value,
      })
    }
    timelineFrameIdx++
  }

  // Interpolate and apply
  for (const [name, state] of currentParams) {
    const progress = Math.min((currentTime - state.startTime) / state.duration, 1.0)
    const eased = progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2
    state.currentValue = state.startValue + (state.targetValue - state.startValue) * eased
    setParam(name, state.currentValue)
    if (progress >= 1.0) currentParams.delete(name)
  }

  timelineRaf = requestAnimationFrame(tickTimeline)
}

export function playParameterTimeline(
  data: AudioPlaybackPayload & { expressions: ParameterTimeline },
  lifecycle?: AudioPlaybackLifecycle,
): void {
  playAudio(data, lifecycle)
  if (data.expressions?.frames) {
    setTimeout(() => {
      timelineFrames = data.expressions.frames
      timelineDuration = data.expressions.total_duration || 0
      timelineStart = performance.now() / 1000
      timelineFrameIdx = 0
      timelinePlaying = true
      currentParams.clear()
      tickTimeline()
    }, 100)
  }
}

export function cancelTimeline(): void {
  timelinePlaying = false
  if (timelineRaf) {
    cancelAnimationFrame(timelineRaf)
    timelineRaf = null
  }
}
