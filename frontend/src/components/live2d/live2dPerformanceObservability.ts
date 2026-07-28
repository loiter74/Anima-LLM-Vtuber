import type { Live2DPerformancePlanV1 } from './live2dPerformanceContract'

export const LIVE2D_PERFORMANCE_OBSERVATION_EVENT =
  'animetta:live2d-performance-observation' as const

type PerformanceLabels = Pick<Live2DPerformancePlanV1, 'source' | 'base' | 'accent'>

export type Live2DPerformanceObservation =
  | ({
      kind: 'plan'
      fallback: 'none' | 'invalid_payload'
    } & PerformanceLabels)
  | ({
      kind: 'activation_delay'
      delayMs: number
    } & PerformanceLabels)
  | {
      kind: 'stale_drop'
      event:
        | 'audio_with_expression'
        | 'audio_stream_start'
        | 'audio_stream_chunk'
        | 'audio_stream_end'
        | 'stop_audio'
    }

export type Live2DPerformanceObserver = (observation: Live2DPerformanceObservation) => void

export const dispatchLive2DPerformanceObservation: Live2DPerformanceObserver = (observation) => {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') return
  window.dispatchEvent(
    new CustomEvent<Live2DPerformanceObservation>(LIVE2D_PERFORMANCE_OBSERVATION_EVENT, {
      detail: observation,
    }),
  )
}
