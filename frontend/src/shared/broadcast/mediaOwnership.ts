export type PublicMediaMode = 'active' | 'muted'
export type PublicMediaOwnerState = 'active' | 'standby' | 'muted'

const PUBLIC_MEDIA_LOCK_NAME = 'animetta:public-media-owner:v2'
const DEFAULT_RETRY_MS = 250
const DEFAULT_ACQUIRE_WAIT_MS = 250

export interface PublicMediaLock {
  readonly name: string
}

export interface PublicMediaLockManager {
  request(
    name: string,
    options: { mode: 'exclusive'; ifAvailable: true },
    callback: (lock: PublicMediaLock | null) => Promise<void> | void,
  ): Promise<void>
}

export interface PublicMediaPlaybackPermit {
  ownerId: string
  fence: number
}

export interface PublicMediaOwnerSnapshot {
  requestedMode: PublicMediaMode
  state: PublicMediaOwnerState
  ownerId: string
  fence: number
}

export interface PublicMediaOwnership {
  readonly requestedMode: PublicMediaMode
  readonly snapshot: PublicMediaOwnerSnapshot
  canPlay(): boolean
  acquirePlayback(): Promise<PublicMediaPlaybackPermit | null>
  validatePlayback(permit: PublicMediaPlaybackPermit): boolean
  subscribe(listener: (snapshot: PublicMediaOwnerSnapshot) => void): () => void
  dispose(): void
}

export interface PublicMediaOwnershipOptions {
  ownerId?: string
  lockManager?: PublicMediaLockManager | null
  retryMs?: number
  acquireWaitMs?: number
}

export function resolvePublicMediaMode(
  search: URLSearchParams,
  defaultMode: PublicMediaMode,
): PublicMediaMode {
  const requested = search.get('media')
  return requested === 'active' || requested === 'muted' ? requested : defaultMode
}

function generatedOwnerId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `owner-${Date.now()}-${Math.random().toString(36).slice(2)}`
  )
}

function browserLockManager(): PublicMediaLockManager | null {
  const navigatorWithLocks = globalThis.navigator as Navigator & {
    locks?: PublicMediaLockManager
  }
  return navigatorWithLocks?.locks ?? null
}

export function createPublicMediaOwnership(
  search: URLSearchParams,
  defaultMode: PublicMediaMode,
  options: PublicMediaOwnershipOptions = {},
): PublicMediaOwnership {
  const requestedMode = resolvePublicMediaMode(search, defaultMode)
  const ownerId = options.ownerId ?? generatedOwnerId()
  const lockManager = options.lockManager === undefined ? browserLockManager() : options.lockManager
  const retryMs = Math.max(10, options.retryMs ?? DEFAULT_RETRY_MS)
  const acquireWaitMs = Math.max(0, options.acquireWaitMs ?? DEFAULT_ACQUIRE_WAIT_MS)
  const listeners = new Set<(snapshot: PublicMediaOwnerSnapshot) => void>()
  let state: PublicMediaOwnerState = requestedMode === 'active' ? 'standby' : 'muted'
  let fence = 0
  let lockHeld = false
  let disposed = false
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let attemptSettlement: Promise<void> | null = null
  let releaseLock: (() => void) | null = null

  const snapshot = (): PublicMediaOwnerSnapshot => ({
    requestedMode,
    state,
    ownerId,
    fence,
  })
  const notify = (): void => {
    const current = snapshot()
    for (const listener of listeners) listener(current)
  }
  const setState = (next: PublicMediaOwnerState, nextFence = fence): void => {
    if (state === next && fence === nextFence) return
    state = next
    fence = nextFence
    notify()
  }
  const scheduleRetry = (): void => {
    if (disposed || requestedMode !== 'active' || !lockManager || retryTimer !== null || lockHeld) {
      return
    }
    retryTimer = globalThis.setTimeout(() => {
      retryTimer = null
      void attemptAcquire()
    }, retryMs)
  }
  const attemptAcquire = (): Promise<void> => {
    if (disposed || requestedMode !== 'active' || !lockManager || lockHeld) {
      return Promise.resolve()
    }
    if (attemptSettlement) return attemptSettlement

    let resolveSettlement: () => void = () => undefined
    const settlement = new Promise<void>((resolve) => {
      resolveSettlement = resolve
    })
    attemptSettlement = settlement
    let settled = false
    const settle = (): void => {
      if (settled) return
      settled = true
      if (attemptSettlement === settlement) attemptSettlement = null
      resolveSettlement()
    }

    try {
      void lockManager
        .request(PUBLIC_MEDIA_LOCK_NAME, { mode: 'exclusive', ifAvailable: true }, async (lock) => {
          if (!lock || disposed || requestedMode !== 'active') {
            settle()
            scheduleRetry()
            return
          }

          const acquiredFence = fence + 1
          const held = new Promise<void>((resolve) => {
            releaseLock = resolve
          })
          lockHeld = true
          setState('active', acquiredFence)
          settle()
          await held
          releaseLock = null
          if (lockHeld && fence === acquiredFence) {
            lockHeld = false
            setState('standby')
          }
        })
        .catch(() => {
          settle()
          setState('standby')
          scheduleRetry()
        })
    } catch {
      settle()
      setState('standby')
      scheduleRetry()
    }
    return settlement
  }

  if (requestedMode === 'active' && lockManager) void attemptAcquire()

  return {
    requestedMode,
    get snapshot(): PublicMediaOwnerSnapshot {
      return snapshot()
    },
    canPlay(): boolean {
      if (disposed || requestedMode !== 'active' || !lockManager) return false
      if (lockHeld && state === 'active') return true
      void attemptAcquire()
      return false
    },
    async acquirePlayback(): Promise<PublicMediaPlaybackPermit | null> {
      if (disposed || requestedMode !== 'active' || !lockManager) return null
      if (!lockHeld) {
        const settlement = attemptAcquire()
        if (acquireWaitMs === 0) await settlement
        else {
          await Promise.race([
            settlement,
            new Promise<void>((resolve) => globalThis.setTimeout(resolve, acquireWaitMs)),
          ])
        }
      }
      return lockHeld && state === 'active' ? { ownerId, fence } : null
    },
    validatePlayback(permit: PublicMediaPlaybackPermit): boolean {
      return (
        !disposed &&
        lockHeld &&
        state === 'active' &&
        permit.ownerId === ownerId &&
        permit.fence === fence
      )
    },
    subscribe(listener): () => void {
      listeners.add(listener)
      listener(snapshot())
      return () => listeners.delete(listener)
    },
    dispose(): void {
      if (disposed) return
      disposed = true
      if (retryTimer !== null) globalThis.clearTimeout(retryTimer)
      retryTimer = null
      lockHeld = false
      releaseLock?.()
      releaseLock = null
      setState(requestedMode === 'active' ? 'standby' : 'muted')
      listeners.clear()
    },
  }
}
