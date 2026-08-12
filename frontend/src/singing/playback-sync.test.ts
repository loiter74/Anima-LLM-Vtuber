import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  SINGING_PLAYBACK_STORAGE_KEY,
  clearSingingPlayback,
  readSingingPlayback,
  resolveSingingPlaybackPosition,
  subscribeSingingPlayback,
  writeSingingPlayback,
} from './playback-sync'

describe('singing playback sync', () => {
  beforeEach(() => localStorage.clear())

  it('persists the dashboard command for a live page opened later', () => {
    writeSingingPlayback({
      taskId: 'sing-task',
      track: 'mix',
      audioUrl: '/api/singing/audio/song_final.wav',
      volumes: [0.1, 0.5],
      durationSeconds: 240,
      state: 'playing',
      positionSeconds: 12,
      updatedAtMs: 1_000,
    })

    expect(readSingingPlayback()).toEqual({
      version: 1,
      taskId: 'sing-task',
      track: 'mix',
      audioUrl: '/api/singing/audio/song_final.wav',
      volumes: [0.1, 0.5],
      durationSeconds: 240,
      state: 'playing',
      positionSeconds: 12,
      updatedAtMs: 1_000,
    })
    expect(resolveSingingPlaybackPosition(readSingingPlayback()!, 4_000)).toBe(15)
  })

  it('rejects malformed persisted state', () => {
    localStorage.setItem(SINGING_PLAYBACK_STORAGE_KEY, '{"state":"playing"}')

    expect(readSingingPlayback()).toBeNull()
  })

  it('only clears the persisted task that reported a playback failure', () => {
    writeSingingPlayback({
      taskId: 'current-task',
      track: 'mix',
      audioUrl: '/current.wav',
      volumes: [],
      durationSeconds: 60,
      state: 'playing',
      positionSeconds: 0,
      updatedAtMs: 1_000,
    })

    expect(clearSingingPlayback('stale-task')).toBe(false)
    expect(readSingingPlayback()?.taskId).toBe('current-task')
    expect(clearSingingPlayback('current-task')).toBe(true)
    expect(readSingingPlayback()).toBeNull()
  })

  it('does not clamp playback when a recent item has unknown duration', () => {
    const snapshot = writeSingingPlayback({
      taskId: 'recent-task',
      track: 'mix',
      audioUrl: '/recent.wav',
      volumes: [],
      durationSeconds: 0,
      state: 'playing',
      positionSeconds: 5,
      updatedAtMs: 1_000,
    })

    expect(resolveSingingPlaybackPosition(snapshot, 4_000)).toBe(8)
  })

  it('notifies another page when dashboard playback changes', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeSingingPlayback(listener)
    const snapshot = {
      version: 1 as const,
      taskId: 'sing-task',
      track: 'vocals' as const,
      audioUrl: '/song_vocals.wav',
      volumes: [0.2],
      durationSeconds: 240,
      state: 'paused' as const,
      positionSeconds: 9,
      updatedAtMs: 2_000,
    }

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: SINGING_PLAYBACK_STORAGE_KEY,
        newValue: JSON.stringify(snapshot),
      }),
    )

    expect(listener).toHaveBeenCalledWith(snapshot)
    unsubscribe()
  })
})
