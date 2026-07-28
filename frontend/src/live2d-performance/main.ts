import type { Live2DStage } from '@/live/live2d-stage'
import { DisposerStack } from '@/review/disposable'
import {
  LIVE2D_PERFORMANCE_OBSERVATION_EVENT,
  type Live2DPerformanceObservation,
} from '@/components/live2d/live2dPerformanceObservability'
import { PERFORMANCE_REVIEW_PLANS } from './catalog'
import { parsePerformanceSamples } from './performanceSamples'
import { createPerformanceSequenceRunner } from './performanceSequence'

export interface Live2DPerformanceReviewHandle {
  element: HTMLElement
  dispose(): void
}

export function mountLive2DPerformanceReview(
  document: Document,
  params: URLSearchParams,
  stage: Live2DStage,
): Live2DPerformanceReviewHandle | null {
  if (params.get('review') !== '1' || params.get('live2dPerformance') !== '1') return null
  const shell = document.querySelector<HTMLElement>('.live-shell')
  if (!shell) throw new Error('Live review surface is unavailable')
  const samples = parsePerformanceSamples(params.get('performanceSamples'))

  const disposers = new DisposerStack()
  const panel = document.createElement('div')
  panel.className = 'live2d-performance-review'
  panel.setAttribute('aria-label', 'Live2D 语义表演评审')
  panel.setAttribute('aria-hidden', 'true')
  panel.hidden = true
  panel.dataset.complete = 'false'
  panel.dataset.lipSync = 'pending'
  panel.dataset.activationObserved = 'false'

  const onPerformanceObservation = (event: Event): void => {
    const observation = (event as CustomEvent<Live2DPerformanceObservation>).detail
    if (observation?.kind === 'activation_delay') panel.dataset.activationObserved = 'true'
  }
  window.addEventListener(LIVE2D_PERFORMANCE_OBSERVATION_EVENT, onPerformanceObservation)
  disposers.add(() =>
    window.removeEventListener(LIVE2D_PERFORMANCE_OBSERVATION_EVENT, onPerformanceObservation),
  )

  const audio = document.createElement('audio')
  audio.id = 'reviewAudio'
  audio.preload = 'auto'
  panel.append(audio)
  shell.append(panel)
  disposers.add(() => panel.remove())

  let disposed = false
  const runner = createPerformanceSequenceRunner({
    length: PERFORMANCE_REVIEW_PLANS.length,
    play(index) {
      const plan = PERFORMANCE_REVIEW_PLANS[index]
      const sample = samples[index]
      panel.dataset.currentBase = plan.base
      panel.dataset.currentAccent = plan.accent
      audio.src = sample.audio
      audio.currentTime = 0
      stage.playReviewAudio(panel, sample.mouthTimeline, plan)
    },
    interrupt() {
      audio.pause()
      stage.cancelReviewAudio()
      panel.dataset.interruption = 'observed'
    },
    complete() {
      panel.dataset.complete = 'true'
      panel.dataset.currentBase = 'calm'
      panel.dataset.currentAccent = 'none'
    },
  })
  const onEnded = (): void => runner.advance()
  audio.addEventListener('ended', onEnded)
  disposers.add(() => audio.removeEventListener('ended', onEnded))
  runner.start()

  return {
    element: panel,
    dispose(): void {
      if (disposed) return
      disposed = true
      runner.dispose()
      audio.pause()
      stage.cancelReviewAudio()
      disposers.dispose()
    },
  }
}
