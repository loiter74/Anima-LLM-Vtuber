/**
 * Audio Store
 * Manages audio recording and playback state using Zustand
 *
 * Architecture:
 * - Subscribes to AudioInteractionManager events
 * - Manager is the SINGLE source of truth for recording state
 * - All components see consistent state via Zustand
 */

import { create } from 'zustand'
import { logger } from '@/shared/utils/logger'
import { getAudioInteractionManager } from '@/features/conversation/services/AudioInteractionManager'

interface AudioState {
  // Recording state
  isRecording: boolean
  volumeLevel: number
  recordingError: string | null

  // Playback state
  isPlaying: boolean
  currentPlaybackUrl: string | null
  playbackError: string | null

  // Actions
  setRecording: (recording: boolean) => void
  setVolumeLevel: (level: number) => void
  setRecordingError: (error: string | null) => void
  setPlaying: (playing: boolean) => void
  setCurrentPlaybackUrl: (url: string | null) => void
  setPlaybackError: (error: string | null) => void
  setError: (error: string | null) => void  // Generic error setter for convenience
  reset: () => void

  // Internal method to setup manager subscription
  _setupManagerSubscription: () => void
}

const initialState = {
  isRecording: false,
  volumeLevel: 0,
  recordingError: null,
  isPlaying: false,
  currentPlaybackUrl: null,
  playbackError: null,
}

// Module-level flag to ensure subscription happens only once
let managerSubscriptionSetup = false
let managerUnsubscribe: (() => void) | null = null

export const useAudioStore = create<AudioState>((set, get) => ({
  ...initialState,

  setRecording: (isRecording) => set({ isRecording }),

  setVolumeLevel: (volumeLevel) => set({ volumeLevel }),

  setRecordingError: (recordingError) => set({ recordingError }),

  setPlaying: (isPlaying) => set({ isPlaying }),

  setCurrentPlaybackUrl: (currentPlaybackUrl) => set({ currentPlaybackUrl }),

  setPlaybackError: (playbackError) => set({ playbackError }),

  setError: (error) => set({ recordingError: error, playbackError: error }),

  reset: () => set(initialState),

  /**
   * Setup subscription to AudioInteractionManager events
   * This should be called once during app initialization
   */
  _setupManagerSubscription: () => {
    // Prevent duplicate subscriptions
    if (managerSubscriptionSetup) {
      logger.debug('[audioStore] Manager subscription already setup')
      return
    }

    logger.info('[audioStore] Setting up manager subscription')
    const manager = getAudioInteractionManager()

    // Subscribe to all manager events and update store state
    managerUnsubscribe = manager.on('recording:started', () => {
      logger.info('[audioStore] Event received: recording:started')
      set({ isRecording: true, recordingError: null })
    })

    manager.on('recording:stopped', () => {
      logger.info('[audioStore] Event received: recording:stopped')
      set({ isRecording: false })
    })

    manager.on('recording:cancelled', () => {
      logger.info('[audioStore] Event received: recording:cancelled')
      set({ isRecording: false })
    })

    manager.on('recording:error', (error: string) => {
      logger.warn('[audioStore] Event received: recording:error:', error)
      set({ isRecording: false, recordingError: error })
    })

    manager.on('audio:playing', () => {
      logger.info('[audioStore] Event received: audio:playing')
      set({ isPlaying: true })
    })

    manager.on('audio:stopped', () => {
      logger.info('[audioStore] Event received: audio:stopped')
      set({ isPlaying: false })
    })

    managerSubscriptionSetup = true
    logger.info('[audioStore] Manager subscription complete')
  },
}))

/**
 * Setup the audio store's manager subscription
 * Call this once during app initialization (e.g., in root layout or main component)
 */
export function setupAudioStoreManagerSubscription(): void {
  const store = useAudioStore.getState()
  store._setupManagerSubscription()
}

/**
 * Cleanup manager subscription (for testing or app shutdown)
 */
export function cleanupAudioStoreManagerSubscription(): void {
  if (managerUnsubscribe) {
    managerUnsubscribe()
    managerUnsubscribe = null
  }
  managerSubscriptionSetup = false
  logger.info('[audioStore] Manager subscription cleaned up')
}
