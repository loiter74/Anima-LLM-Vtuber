export const SINGING_PLAYBACK_STORAGE_KEY = 'animetta:singing-playback:v1'

export type SingingTrack = 'mix' | 'vocals' | 'original'
export type SingingPlaybackState = 'playing' | 'paused' | 'completed'

export interface SingingPlaybackSnapshot {
  version: 1
  taskId: string
  track: SingingTrack
  audioUrl: string
  volumes: number[]
  durationSeconds: number
  state: SingingPlaybackState
  positionSeconds: number
  updatedAtMs: number
}

type SingingPlaybackUpdate = Omit<SingingPlaybackSnapshot, 'version'>

function parseSingingPlayback(value: string | null): SingingPlaybackSnapshot | null {
  if (!value) return null
  try {
    const candidate = JSON.parse(value) as Partial<SingingPlaybackSnapshot>
    if (
      candidate.version !== 1 ||
      typeof candidate.taskId !== 'string' ||
      !candidate.taskId ||
      !['mix', 'vocals', 'original'].includes(candidate.track ?? '') ||
      typeof candidate.audioUrl !== 'string' ||
      !candidate.audioUrl ||
      !Array.isArray(candidate.volumes) ||
      !candidate.volumes.every(Number.isFinite) ||
      !Number.isFinite(candidate.durationSeconds) ||
      (candidate.durationSeconds ?? -1) < 0 ||
      !['playing', 'paused', 'completed'].includes(candidate.state ?? '') ||
      !Number.isFinite(candidate.positionSeconds) ||
      !Number.isFinite(candidate.updatedAtMs)
    ) {
      return null
    }
    return candidate as SingingPlaybackSnapshot
  } catch {
    return null
  }
}

export function writeSingingPlayback(update: SingingPlaybackUpdate): SingingPlaybackSnapshot {
  const snapshot: SingingPlaybackSnapshot = { version: 1, ...update }
  try {
    window.localStorage.setItem(SINGING_PLAYBACK_STORAGE_KEY, JSON.stringify(snapshot))
  } catch (error) {
    console.warn('[singing] Unable to persist playback state', error)
  }
  return snapshot
}

export function readSingingPlayback(): SingingPlaybackSnapshot | null {
  try {
    return parseSingingPlayback(window.localStorage.getItem(SINGING_PLAYBACK_STORAGE_KEY))
  } catch {
    return null
  }
}

export function subscribeSingingPlayback(
  listener: (snapshot: SingingPlaybackSnapshot) => void,
): () => void {
  const onStorage = (event: StorageEvent): void => {
    if (event.key !== SINGING_PLAYBACK_STORAGE_KEY) return
    const snapshot = parseSingingPlayback(event.newValue)
    if (snapshot) listener(snapshot)
  }
  window.addEventListener('storage', onStorage)
  return () => window.removeEventListener('storage', onStorage)
}

export function resolveSingingPlaybackPosition(
  snapshot: SingingPlaybackSnapshot,
  nowMs = Date.now(),
): number {
  const elapsed =
    snapshot.state === 'playing' ? Math.max(0, nowMs - snapshot.updatedAtMs) / 1000 : 0
  const position = Math.max(0, snapshot.positionSeconds + elapsed)
  return snapshot.durationSeconds > 0 ? Math.min(snapshot.durationSeconds, position) : position
}
