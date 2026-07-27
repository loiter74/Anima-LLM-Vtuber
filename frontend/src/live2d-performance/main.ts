import type { Live2DStage } from '@/live/live2d-stage'
import { DisposerStack } from '@/review/disposable'
import { PERFORMANCE_ACCENTS, PERFORMANCE_BASES, PERFORMANCE_REVIEW_PLANS } from './catalog'

export interface Live2DPerformanceReviewHandle {
  element: HTMLElement
  dispose(): void
}

function requiredParameter(params: URLSearchParams, name: string): string {
  const value = params.get(name)?.trim()
  if (!value) throw new Error(`Missing review parameter: ${name}`)
  return value
}

export function mountLive2DPerformanceReview(
  document: Document,
  params: URLSearchParams,
  stage: Live2DStage,
  volumes: readonly number[],
): Live2DPerformanceReviewHandle | null {
  if (params.get('review') !== '1' || params.get('live2dPerformance') !== '1') return null
  const shell = document.querySelector<HTMLElement>('.live-shell')
  if (!shell) throw new Error('Live review surface is unavailable')

  const disposers = new DisposerStack()
  const panel = document.createElement('aside')
  panel.className = 'live2d-performance-review'
  panel.setAttribute('aria-label', 'Live2D 语义表演评审')
  panel.dataset.complete = 'false'
  panel.dataset.lipSync = 'pending'

  const title = document.createElement('h2')
  title.textContent = '语义表演控制'
  const current = document.createElement('p')
  current.className = 'live2d-performance-current'
  const catalog = document.createElement('p')
  catalog.className = 'live2d-performance-catalog'
  catalog.textContent = [...PERFORMANCE_BASES, ...PERFORMANCE_ACCENTS].join(' · ')
  const audio = document.createElement('audio')
  audio.id = 'reviewAudio'
  audio.preload = 'auto'
  audio.src = requiredParameter(params, 'audio')
  panel.append(title, current, catalog, audio)
  shell.append(panel)
  disposers.add(() => panel.remove())

  let index = 0
  let timer: number | null = null
  let disposed = false
  let interruptionExercised = false
  const playCurrent = (): void => {
    if (disposed) return
    const plan = PERFORMANCE_REVIEW_PLANS[index]
    panel.dataset.currentBase = plan.base
    panel.dataset.currentAccent = plan.accent
    current.textContent = `${index + 1}/${PERFORMANCE_REVIEW_PLANS.length} · ${plan.base} · ${plan.accent}`
    audio.currentTime = 0
    stage.playReviewAudio(panel, volumes, plan)
    if (!interruptionExercised) {
      interruptionExercised = true
      timer = window.setTimeout(() => {
        audio.pause()
        stage.cancelReviewAudio()
        panel.dataset.interruption = 'observed'
        timer = window.setTimeout(playCurrent, 450)
      }, 650)
    }
  }
  const onEnded = (): void => {
    index += 1
    if (index >= PERFORMANCE_REVIEW_PLANS.length) {
      panel.dataset.complete = 'true'
      panel.dataset.currentBase = 'calm'
      panel.dataset.currentAccent = 'none'
      current.textContent = '完成 · 已回到 calm'
      return
    }
    timer = window.setTimeout(playCurrent, 450)
  }
  audio.addEventListener('ended', onEnded)
  disposers.add(() => audio.removeEventListener('ended', onEnded))
  playCurrent()

  return {
    element: panel,
    dispose(): void {
      if (disposed) return
      disposed = true
      if (timer !== null) window.clearTimeout(timer)
      audio.pause()
      disposers.dispose()
    },
  }
}
