import { io, Socket } from 'socket.io-client'
import { onMounted } from 'vue'
import { useConnectionStore } from '@/stores/connection'
import { useModelLoadingStore } from '@/stores/modelLoading'
import { useSingingStore } from '@/stores/singing'
import type { ModelStatusPayload } from '@/types/model-loading'
import type { PipelineStage } from '@/types/singing'
import { Events, type SingCompletePayload } from '@/constants/socket-events'
import { checkAuthenticatedSession, type AuthStatus } from '@/auth/session'

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
    socket = io(window.location.origin, {
      path: '/socket.io/',
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionDelay: 3000,
      reconnectionAttempts: Infinity,
      timeout: 120000,
      autoConnect: false,
      withCredentials: true,
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
    socket.on(
      Events.SING.PROGRESS,
      (data: { stage: PipelineStage; progress: number; message?: string }) => {
        singStore.setProgress(data.stage, data.progress, data.message || '')
      },
    )
    socket.on(Events.SING.COMPLETE, (data: SingCompletePayload) => {
      singStore.setResult({
        task_id: data.task_id,
        audio_url: data.audio_url,
        subtitle_url: data.subtitle_url || '',
        tts_audio_url: data.tts_audio_url || '',
        vocals_url: data.vocals_url || '',
        original_url: data.original_url || '',
        video_title: data.video_title || '',
        duration: data.duration,
        lyrics: data.lyrics || [],
        volumes: data.volumes || [],
        voice_conversion_applied: data.voice_conversion_applied,
        voice_provider: data.voice_provider,
        voice_model: data.voice_model,
        voice_revision: data.voice_revision,
        voice_name: data.voice_name,
      })
    })
    socket.on(Events.SING.ERROR, (data: { error: string }) => {
      singStore.setError(data.error)
    })
    socket.on(Events.SING.LYRICS_READY, (data: { message?: string }) => {
      singStore.setProgress('waiting_lyrics', 0, data.message || 'Lyrics ready')
    })

    _initialized = true
  }

  onMounted(() => {
    store.setAuthStatus('checking')
    store.setStatus(socket?.connected ? 'connected' : 'disconnected')
    void ensureAuthenticatedSession()
  })

  return { socket, connectionStatus: store.status }
}

/** Get the global socket instance for use in composables */
export function getSocket(): Socket | null {
  return socket
}

export async function ensureAuthenticatedSession(): Promise<AuthStatus> {
  const store = useConnectionStore()
  if (!socket) {
    store.setAuthStatus('unavailable')
    return 'unavailable'
  }
  const authStatus = await checkAuthenticatedSession()
  store.setAuthStatus(authStatus)
  if (authStatus === 'authenticated') {
    store.setStatus(socket.connected ? 'connected' : 'connecting')
    socket.connect()
  } else {
    socket.disconnect()
    store.setStatus('disconnected')
  }
  return authStatus
}
