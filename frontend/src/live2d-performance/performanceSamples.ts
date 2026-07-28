import {
  LIVE2D_PERFORMANCE_BASES,
  type Live2DPerformanceBase,
} from '@/components/live2d/live2dPerformanceContract'

export interface PerformanceSample {
  base: Live2DPerformanceBase
  audio: string
  mouthTimeline: readonly number[]
}

export function parsePerformanceSamples(raw: string | null): readonly PerformanceSample[] {
  if (!raw) throw new Error('Missing review parameter: performanceSamples')
  const parsed: unknown = JSON.parse(raw)
  if (!Array.isArray(parsed) || parsed.length !== LIVE2D_PERFORMANCE_BASES.length) {
    throw new Error('Invalid performance sample catalog')
  }
  return LIVE2D_PERFORMANCE_BASES.map((base) => {
    const matches = parsed.filter(
      (candidate): candidate is Record<string, unknown> =>
        typeof candidate === 'object' && candidate !== null && candidate.base === base,
    )
    const sample = matches.length === 1 ? matches[0] : null
    if (
      !sample ||
      typeof sample.audio !== 'string' ||
      !sample.audio ||
      !Array.isArray(sample.mouthTimeline) ||
      sample.mouthTimeline.length === 0 ||
      !sample.mouthTimeline.every(
        (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1,
      )
    ) {
      throw new Error(`Invalid performance sample: ${base}`)
    }
    return {
      base,
      audio: sample.audio,
      mouthTimeline: sample.mouthTimeline as number[],
    }
  })
}
