/**
 * Connection Store
 * Manages Socket.IO connection state using Zustand
 */

import { create } from 'zustand'

type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

interface ConnectionState {
  // State
  status: ConnectionStatus
  sessionId: string | null
  error: string | null

  // Actions
  setStatus: (status: ConnectionStatus) => void
  setSessionId: (id: string | null) => void
  setError: (error: string | null) => void
  reset: () => void
}

const initialState = {
  status: 'disconnected' as ConnectionStatus,
  sessionId: null,
  error: null,
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  ...initialState,

  setStatus: (status) => set({ status }),

  setSessionId: (id) => set({ sessionId: id }),

  setError: (error) => set({ error }),

  reset: () => set(initialState),
}))
