/**
 * useAudioPlayer Hook
 * Manages audio playback state and operations
 */

import { useCallback, useRef, useEffect } from 'react'
import { AudioPlayer } from '../services/AudioPlayer'
import { useAudioStore } from '@/shared/state/stores/audioStore'
import { logger } from '@/shared/utils/logger'
import type { AudioPlayerOptions } from '../types'

export interface UseAudioPlayerReturn {
  playAudio: (base64: string, format?: string) => Promise<void>
  stopAudio: () => void
  stopGlobalAudio: () => void
}

/**
 * Hook for audio playback functionality
 */
export function useAudioPlayer(
  onPlayStart?: () => void,
  onPlayEnd?: () => void
): UseAudioPlayerReturn {
  const { setPlaying, setError } = useAudioStore()

  // Create player instance (singleton)
  const playerRef = useRef<AudioPlayer | null>(null)

  useEffect(() => {
    if (!playerRef.current) {
      playerRef.current = new AudioPlayer({
        onPlayStart: () => {
          logger.debug('[useAudioPlayer] 开始播放')
          setPlaying(true)
          onPlayStart?.()
        },
        onPlayEnd: () => {
          logger.debug('[useAudioPlayer] 播放结束')
          setPlaying(false)
          onPlayEnd?.()
        },
        onError: (error) => {
          logger.error('[useAudioPlayer] 播放错误:', error)
          setError(error.message)
        },
      })
    }

    return () => {
      logger.debug('[useAudioPlayer] Cleaning up player')
      playerRef.current?.destroy()
      playerRef.current = null
    }
  }, []) // ✅ 空依赖数组，只运行一次

  // Play audio from base64
  const playAudio = useCallback(
    async (base64: string, format?: string) => {
      if (!playerRef.current) return
      await playerRef.current.play(base64, format)
    },
    []
  )

  // Stop current playback
  const stopAudio = useCallback(() => {
    if (!playerRef.current) return
    playerRef.current.stop()
    setPlaying(false)
  }, [setPlaying])

  // Stop any globally playing audio (useful for interrupt)
  const stopGlobalAudio = useCallback(() => {
    AudioPlayer.stopGlobalAudio()
    setPlaying(false)
  }, [setPlaying])

  return {
    playAudio,
    stopAudio,
    stopGlobalAudio,
  }
}
