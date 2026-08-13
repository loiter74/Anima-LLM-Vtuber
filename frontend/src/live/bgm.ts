const DEFAULT_BGM_SRC = '/audio/bgm/live-default.mp3'
const DEFAULT_VOLUME = 0.12
const DUCKED_VOLUME = 0.035

export interface LiveBgmController {
  duck(): void
  release(): void
  unlock(): void
  dispose(): void
}

function configuredVolume(search: URLSearchParams): number {
  const value = Number(search.get('bgmVolume') ?? DEFAULT_VOLUME)
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : DEFAULT_VOLUME
}

export function createLiveBgmController(
  document: Document,
  search: URLSearchParams,
): LiveBgmController {
  const audio = document.getElementById('bgmAudio') as HTMLAudioElement | null
  const status = document.getElementById('audioStatus')
  const requested = search.get('bgm')
  const enabled = Boolean(audio) && requested !== 'off'
  const normalVolume = configuredVolume(search)
  const duckedVolume = Math.min(normalVolume, DUCKED_VOLUME)
  let timer: ReturnType<typeof setInterval> | null = null
  let disposed = false

  const onError = (): void => {
    if (status) status.dataset.bgmState = 'missing'
  }

  if (audio && enabled) {
    audio.src = requested || DEFAULT_BGM_SRC
    audio.loop = true
    audio.volume = normalVolume
    audio.addEventListener('error', onError)
    if (status) status.dataset.bgmState = 'pending'
    void audio.play().then(
      () => {
        if (status) status.dataset.bgmState = 'playing'
      },
      () => {
        if (status) status.dataset.bgmState = 'blocked'
      },
    )
  } else if (status) {
    status.dataset.bgmState = 'off'
  }

  const transitionTo = (target: number, durationMs: number): void => {
    if (!audio || !enabled || disposed) return
    if (timer) clearInterval(timer)
    const start = audio.volume
    const startedAt = performance.now()
    timer = setInterval(() => {
      const progress = Math.min(1, (performance.now() - startedAt) / durationMs)
      audio.volume = start + (target - start) * progress
      if (progress === 1 && timer) {
        clearInterval(timer)
        timer = null
      }
    }, 25)
  }

  return {
    duck(): void {
      transitionTo(duckedVolume, 150)
    },
    release(): void {
      transitionTo(normalVolume, 300)
    },
    unlock(): void {
      if (!audio || !enabled || !audio.paused) return
      void audio.play().then(
        () => {
          if (status) status.dataset.bgmState = 'playing'
        },
        () => undefined,
      )
    },
    dispose(): void {
      disposed = true
      if (timer) clearInterval(timer)
      timer = null
      if (audio) {
        audio.removeEventListener('error', onError)
        audio.pause()
        audio.removeAttribute('src')
        audio.load()
      }
    },
  }
}
