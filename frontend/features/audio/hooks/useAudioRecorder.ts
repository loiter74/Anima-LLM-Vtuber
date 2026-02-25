/**
 * useAudioRecorder Hook
 * Manages audio recording state and operations
 */

import { useState, useCallback, useEffect } from 'react'
import { AudioRecorder } from '../services/AudioRecorder'
import { useAudioStore } from '@/shared/state/stores/audioStore'
import { logger } from '@/shared/utils/logger'
import type { AudioRecorderOptions } from '../types'

export interface UseAudioRecorderOptions extends AudioRecorderOptions {
  onError?: (error: string) => void
}

export interface UseAudioRecorderReturn {
  isRecording: boolean
  startRecording: () => Promise<void>
  stopRecording: () => void
}

/**
 * Hook for audio recording functionality
 */
export function useAudioRecorder(
  onAudioData: (pcmData: Int16Array) => void,
  options: UseAudioRecorderOptions = {}
): UseAudioRecorderReturn {
  const { setRecording, setError } = useAudioStore()
  const [recorder] = useState(() => new AudioRecorder(options))

  // Update error callback when options change
  useEffect(() => {
    if (options.onError) {
      // Store callback for use in error handling
      ;(recorder as any)._onError = options.onError
    }
  }, [options.onError, recorder])

  // Start recording
  const startRecording = useCallback(async () => {
    try {
      await recorder.start((pcmData) => {
        onAudioData(pcmData)
        // Notify audio chunk sent (for VolumeMonitor)
        window.dispatchEvent(new CustomEvent('audio-chunk-sent'))
      })

      setRecording(true)

      // Notify recording state change
      ;(window as any).__isRecording = true
      window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: true }))

      logger.debug('[useAudioRecorder] ✅ 录音已启动')
    } catch (err) {
      logger.error('[useAudioRecorder] 录音启动失败:', err)
      const errorMessage = err instanceof Error ? err.message : '无法访问麦克风'
      setError(errorMessage)
      if ((recorder as any)._onError) {
        (recorder as any)._onError(errorMessage)
      }
      throw err
    }
  }, [recorder, onAudioData, setRecording, setError])

  // Stop recording
  const stopRecording = useCallback(() => {
    recorder.stop()
    setRecording(false)

    // Notify recording state change
    ;(window as any).__isRecording = false
    window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: false }))

    logger.debug('[useAudioRecorder] ✅ 录音已停止')
  }, [recorder, setRecording])

  return {
    isRecording: recorder.recording,
    startRecording,
    stopRecording,
  }
}
