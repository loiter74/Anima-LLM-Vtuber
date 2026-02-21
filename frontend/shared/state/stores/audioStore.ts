/**
 * Audio Store
 * Manages audio recording and playback state using Zustand
 */

import { create } from 'zustand'

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
}

const initialState = {
  isRecording: false,
  volumeLevel: 0,
  recordingError: null,
  isPlaying: false,
  currentPlaybackUrl: null,
  playbackError: null,
}

export const useAudioStore = create<AudioState>((set) => ({
  ...initialState,

  setRecording: (isRecording) => set({ isRecording }),

  setVolumeLevel: (volumeLevel) => set({ volumeLevel }),

  setRecordingError: (recordingError) => set({ recordingError }),

  setPlaying: (isPlaying) => set({ isPlaying }),

  setCurrentPlaybackUrl: (currentPlaybackUrl) => set({ currentPlaybackUrl }),

  setPlaybackError: (playbackError) => set({ playbackError }),

  setError: (error) => set({ recordingError: error, playbackError: error }),

  reset: () => set(initialState),
}))
