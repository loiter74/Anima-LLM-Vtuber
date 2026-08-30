import type { PublicMediaMode, PublicMediaOwnership } from '@/shared/broadcast/mediaOwnership'

const DEFAULT_BGM_SRC = '/audio/bgm/live-default.mp3'
const DEFAULT_VOLUME = 0.12
const DUCKED_VOLUME = 0.035

export interface LiveBgmController {
  duck(): void
  release(): void
  unlock(): void
  dispose(): void
}

export interface LiveBgmControllerOptions {
  mediaMode?: PublicMediaMode
  ownership?: PublicMediaOwnership
}

function configuredVolume(search: URLSearchParams): number {
  const value = Number(search.get('bgmVolume') ?? DEFAULT_VOLUME)
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : DEFAULT_VOLUME
}

export function createLiveBgmController(
  document: Document,
  search: URLSearchParams,
  options: LiveBgmControllerOptions = {},
): LiveBgmController {
  const audio = document.getElementById('bgmAudio') as HTMLAudioElement | null
  const status = document.getElementById('audioStatus')
  const requested = search.get('bgm')
  const requestedMode = options.ownership?.requestedMode ?? options.mediaMode ?? 'active'
  const configured = Boolean(audio) && requested !== 'off' && requestedMode === 'active'
  const normalVolume = configuredVolume(search)
  const duckedVolume = Math.min(normalVolume, DUCKED_VOLUME)
  let timer: ReturnType<typeof setInterval> | null = null
  let disposed = false

  const onError = (): void => {
    if (status) status.dataset.bgmState = 'missing'
  }

  if (audio && configured) {
    audio.src = requested || DEFAULT_BGM_SRC
    audio.loop = true
    audio.volume = normalVolume
    audio.addEventListener('error', onError)
  }

  const startForOwner = (): void => {
    if (!audio || !configured || disposed) return
    const play = (permit: Awaited<ReturnType<PublicMediaOwnership['acquirePlayback']>>): void => {
      if (options.ownership && (!permit || !options.ownership.validatePlayback(permit))) {
        audio.pause()
        if (status) status.dataset.bgmState = 'standby'
        return
      }
      if (status) status.dataset.bgmState = 'pending'
      void audio.play().then(
        () => {
          if (options.ownership && (!permit || !options.ownership.validatePlayback(permit))) {
            audio.pause()
            if (status) status.dataset.bgmState = 'standby'
            return
          }
          if (status) status.dataset.bgmState = 'playing'
        },
        () => {
          if (status) status.dataset.bgmState = 'blocked'
        },
      )
    }
    if (options.ownership) void options.ownership.acquirePlayback().then(play)
    else play(null)
  }

  const unsubscribeOwnership = options.ownership?.subscribe((snapshot) => {
    if (!audio || !configured) return
    if (snapshot.state === 'active') {
      startForOwner()
      return
    }
    audio.pause()
    if (status) status.dataset.bgmState = snapshot.state
  })
  if (!options.ownership) startForOwner()
  if (!configured && status) {
    status.dataset.bgmState = requestedMode === 'muted' ? 'muted' : 'off'
  }

  const transitionTo = (target: number, durationMs: number): void => {
    if (!audio || !configured || disposed || options.ownership?.snapshot.state === 'standby') return
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
      if (!audio || !configured || !audio.paused) return
      startForOwner()
    },
    dispose(): void {
      disposed = true
      if (timer) clearInterval(timer)
      timer = null
      unsubscribeOwnership?.()
      if (audio) {
        audio.removeEventListener('error', onError)
        audio.pause()
        audio.removeAttribute('src')
        audio.load()
      }
    },
  }
}
