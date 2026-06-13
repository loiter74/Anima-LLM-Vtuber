import { io, Socket } from 'socket.io-client'
import { ref, onMounted, onUnmounted } from 'vue'
import { useConnectionStore } from '@/stores/connection'
import { useModelLoadingStore } from '@/stores/modelLoading'
import { useSingingStore } from '@/stores/singing'
import type { ModelStatusPayload } from '@/types/model-loading'
import type { ConnectionStatus } from '@/types/socket-events'
import type { PipelineStage, SongResult } from '@/types/singing'
import { Events } from '@/constants/socket-events'

// Connect via same-origin (nginx in Docker, Vite proxy in dev) to avoid
// CORS + WSL2 WebSocket relay issues. Set VITE_API_URL to override (e.g. ngrok).
const SOCKET_URL = import.meta.env.VITE_API_URL || ''

let socket: Socket | null = null
let _initialized = false
let _connectFailures = 0
const MAX_FAILURES_BEFORE_ERROR = 3

/**
 * Create a singleton Socket.IO connection to the Animetta backend.
 * Call once at app startup. Composables import the socket ref for use.
 */
export function useSocket() {
  const store = useConnectionStore()

  if (!_initialized && !socket) {
    const url = SOCKET_URL || window.location.origin
    socket = io(url, {
      path: '/socket.io/',
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionDelay: 3000,
      reconnectionAttempts: Infinity,
      timeout: 120000
    })

    socket.on('connect', () => {
      _connectFailures = 0
      store.setStatus('connected')
    })

    socket.on('disconnect', () => {
      store.setStatus('disconnected')
    })

    socket.on('connect_error', () => {
      _connectFailures++
      if (_connectFailures >= MAX_FAILURES_BEFORE_ERROR) {
        store.setStatus('error', `Connection failed after ${_connectFailures} attempts`)
      } else {
        // First few failures are normal (WebSocket → polling fallback)
        store.setStatus('connecting')
      }
    })

    // Listen for model loading status
    const modelStore = useModelLoadingStore()
    socket.on(Events.SYSTEM.MODEL_STATUS, (payload: ModelStatusPayload) => {
      modelStore.updateModelStatus(payload)
    })

    // Clear loading state on reconnect
    socket.on('connect', () => {
      // Don't clear on reconnect - warmup may still be in progress
    })

    // Register singing event listeners globally (survive tab switches)
    const singStore = useSingingStore()
    socket.on(Events.SING.PROGRESS, (data: any) => {
      singStore.setProgress(data.stage, data.progress, data.message || '')
    })
    socket.on(Events.SING.COMPLETE, (data: any) => {
      singStore.setResult({
        audio_url: data.audio_url,
        subtitle_url: data.subtitle_url || '',
        tts_audio_url: data.tts_audio_url || '',
        vocals_url: data.vocals_url || '',
        original_url: data.original_url || '',
        video_title: data.video_title || '',
        duration: data.duration,
        lyrics: data.lyrics || [],
        volumes: data.volumes || [],
      })
    })
    socket.on(Events.SING.ERROR, (data: any) => {
      singStore.setError(data.error)
    })
    socket.on(Events.SING.LYRICS_READY, (data: any) => {
      singStore.setProgress('waiting_lyrics' as PipelineStage, 0, data.message || 'Lyrics ready')
    })

    _initialized = true
  }

  onMounted(() => {
    // Show connecting state until first connect/error event fires
    store.setStatus(socket?.connected ? 'connected' : 'connecting')
  })

  return { socket, connectionStatus: store.status }
}

/** Get the global socket instance for use in composables */
export function getSocket(): Socket | null {
  return socket
}
