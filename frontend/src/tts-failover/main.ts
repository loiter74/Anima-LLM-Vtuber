function requiredParameter(params: URLSearchParams, name: string): string {
  const value = params.get(name)?.trim()
  if (!value) throw new Error(`Missing review parameter: ${name}`)
  return value
}

const COLLAPSE_DELAY_MS = 1_400
const GAP_CLEARANCE_PX = 12

export interface TtsFailoverReviewNotificationHandle {
  element: HTMLElement
  audio: HTMLAudioElement
  dispose(): void
}

function positionNotification(document: Document, notification: HTMLElement): void {
  const statusRail = document.querySelector<HTMLElement>('.status-rail')
  const danmakuPanel = document.querySelector<HTMLElement>('.danmaku-panel')
  if (!statusRail || !danmakuPanel) return

  const safeGapLeft = statusRail.getBoundingClientRect().right + GAP_CLEARANCE_PX
  const safeGapRight = danmakuPanel.getBoundingClientRect().left - GAP_CLEARANCE_PX
  const safeGapWidth = Math.max(0, safeGapRight - safeGapLeft)
  notification.style.setProperty(
    '--tts-failover-island-left',
    `${safeGapLeft + safeGapWidth / 2}px`,
  )
  notification.style.setProperty('--tts-failover-island-max-width', `${safeGapWidth}px`)
}

export function mountTtsFailoverReviewNotification(
  document: Document,
  params: URLSearchParams,
  options: { autoplay?: boolean } = {},
): TtsFailoverReviewNotificationHandle | null {
  if (params.get('review') !== '1' || params.get('ttsFailover') !== '1') return null

  const existing = document.querySelector<HTMLElement>('[data-tts-failover-review]')
  if (existing) return null

  const liveShell = document.querySelector<HTMLElement>('.live-shell')
  if (!liveShell) throw new Error('Live review surface is unavailable')

  const backend = requiredParameter(params, 'backend')
  const firstAudio = requiredParameter(params, 'firstAudio')
  const rtf = requiredParameter(params, 'rtf')
  const sampleRate = requiredParameter(params, 'sampleRate')
  const provider = requiredParameter(params, 'provider')
  const audioUrl = requiredParameter(params, 'audio')

  const notification = document.createElement('aside')
  notification.className = 'tts-failover-notification'
  notification.dataset.ttsFailoverReview = 'true'
  notification.dataset.sampleRate = sampleRate
  notification.dataset.provider = provider
  const view = document.defaultView
  const reducedMotion = view?.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  notification.dataset.state = reducedMotion ? 'collapsed' : 'expanded'
  notification.setAttribute('aria-label', 'TTS 降级接管通知')
  notification.setAttribute('aria-live', 'polite')
  notification.setAttribute('role', 'status')

  const indicator = document.createElement('span')
  indicator.className = 'tts-failover-indicator'
  indicator.setAttribute('aria-hidden', 'true')

  const copy = document.createElement('div')
  copy.className = 'tts-failover-copy'

  const title = document.createElement('p')
  title.className = 'tts-failover-title'
  title.textContent = '云端语音暂不可用'

  const detail = document.createElement('p')
  detail.className = 'tts-failover-detail'

  const takeover = document.createElement('span')
  takeover.className = 'tts-failover-takeover'
  takeover.textContent = '本地语音已接管'

  const metrics = document.createElement('span')
  metrics.className = 'tts-failover-metrics'
  metrics.textContent = `${backend} · 首包 ${firstAudio}s · RTF ${rtf}`

  const collapsedLabel = document.createElement('span')
  collapsedLabel.className = 'tts-failover-collapsed-label'
  collapsedLabel.textContent = '本地语音接管'

  const audio = document.createElement('audio')
  audio.id = 'reviewAudio'
  audio.preload = 'auto'
  audio.dataset.complete = 'false'
  audio.src = audioUrl
  const onEnded = (): void => {
    audio.dataset.complete = 'true'
  }
  const onError = (): void => {
    audio.dataset.complete = 'error'
  }
  audio.addEventListener('ended', onEnded, { once: true })
  audio.addEventListener('error', onError, { once: true })

  detail.append(takeover, metrics)
  copy.append(title, detail)
  notification.append(indicator, copy, collapsedLabel, audio)
  liveShell.append(notification)

  positionNotification(document, notification)
  const onResize = (): void => positionNotification(document, notification)
  view?.addEventListener('resize', onResize)
  const ResizeObserverConstructor = view?.ResizeObserver
  const resizeObserver = ResizeObserverConstructor ? new ResizeObserverConstructor(onResize) : null
  const statusRail = document.querySelector<HTMLElement>('.status-rail')
  const danmakuPanel = document.querySelector<HTMLElement>('.danmaku-panel')
  if (statusRail) resizeObserver?.observe(statusRail)
  if (danmakuPanel) resizeObserver?.observe(danmakuPanel)

  const collapseTimer = reducedMotion
    ? null
    : view?.setTimeout(() => {
        notification.dataset.state = 'collapsed'
      }, COLLAPSE_DELAY_MS)
  let disposed = false
  const handle: TtsFailoverReviewNotificationHandle = {
    element: notification,
    audio,
    dispose(): void {
      if (disposed) return
      disposed = true
      if (collapseTimer != null) view?.clearTimeout(collapseTimer)
      resizeObserver?.disconnect()
      view?.removeEventListener('resize', onResize)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('error', onError)
    },
  }

  if (options.autoplay !== false) {
    void audio.play().catch(() => {
      audio.dataset.complete = 'blocked'
    })
  }
  return handle
}
