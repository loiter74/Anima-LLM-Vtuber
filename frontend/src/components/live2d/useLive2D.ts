import { onMounted, onUnmounted, type Ref } from 'vue'
import type { Live2DAction } from '@/types/live2d'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'
import type {
  AudioStreamChunkEvent,
  AudioStreamEndEvent,
  AudioStreamStartEvent,
  AudioWithExpressionEvent,
  ChatIdentity,
} from '@/types/socket-events'
import { isCurrentChatTask } from '@/composables/chatTaskGate'

// ===== Public exports for backward compatibility =====
export { MODEL_PATH } from './useLive2DModel'
export type { ScaleStrategy } from './useLive2DModel'

// ===== Import sub-composable internals =====
import { getApp, initPixiApp, handlePixiResize, destroyPixiApp } from './usePixiApp'
import {
  loadModel,
  unloadModel,
  setExpression,
  playMotion,
  getModel,
  retryLoad,
} from './useLive2DModel'
import { tickLipSync, setMouthTarget } from './useLipSync'
import {
  endAudioStream,
  playAudio,
  pushAudioStreamChunk,
  startAudioStream,
  stopAudio,
} from './useAudioPlayback'
import { playParameterTimeline, setParam, cancelTimeline } from './useParameterTimeline'
import {
  isLoaded,
  isLoading,
  loadError,
  modelInfo,
  isDragging,
  startDrag,
  onDrag,
  stopDrag,
  focus as focusFn,
  zoom as zoomFn,
  resetView as resetViewFn,
  setScaleStrategy as setScaleStrategyFn,
} from './useInteraction'

type Live2DSocket = NonNullable<ReturnType<typeof getSocket>>

let socketListenerOwners = 0
let listenerSocket: Live2DSocket | null = null
let live2dActionListener: ((data: unknown) => void) | null = null
let audioWithExpressionListener: ((data: AudioWithExpressionEvent) => void) | null = null
let audioStreamStartListener: ((data: AudioStreamStartEvent) => void) | null = null
let audioStreamChunkListener: ((data: AudioStreamChunkEvent) => void) | null = null
let audioStreamEndListener: ((data: AudioStreamEndEvent) => void) | null = null
let stopAudioListener: ((data: ChatIdentity) => void) | null = null
let disconnectListener: (() => void) | null = null

// ===== Main Composable =====

/**
 * Unified composable entry point — wires all sub-composables together
 * while maintaining the identical public API surface.
 */
export function useLive2D(canvasRef: Ref<HTMLCanvasElement | null>) {
  let ownsSocketListeners = false

  // ===== Init =====

  async function init(): Promise<void> {
    console.log('[Live2D] init() called, canvasRef.value:', canvasRef.value)
    if (!canvasRef.value) {
      console.error('[Live2D] Canvas ref is null in init()')
      return
    }

    try {
      await initPixiApp(canvasRef)

      const app = getApp()
      if (app) {
        // NOTE: pixi.js internally uses synchronous gl.readPixels() which
        // triggers "GPU stall due to ReadPixels" warnings in some GPU drivers.
        // This is a known limitation of the pixi-live2d-display rendering
        // pipeline. Mitigation: reduce ticker FPS if warnings are excessive:
        //   app.ticker.maxFPS = 30
        // See: .gstack/qa-reports/qa-report-localhost-3000-2026-06-02.md (ISSUE-008)
        app.ticker.add(tickLipSync)
        setupSocketListeners()
      }
    } catch (e) {
      loadError.value = 'pixi.js 初始化失败: ' + (e as Error).message
      isLoading.value = false
    }
  }

  // ===== Resize =====

  /**
   * Handle container resize (e.g. DevTools open/close).
   * Resizes renderer and adjusts model position proportionally.
   * Does NOT re-center — preserves user's drag offset.
   * Does NOT change scale.
   */
  function handleResize(): void {
    const result = handlePixiResize()
    if (!result) return

    const model = getModel()
    const app = getApp()
    if (model && app) {
      model.x *= app.screen.width / result.oldW
      model.y *= app.screen.height / result.oldH
    }
  }

  // ===== Execute Action =====

  function executeAction(action: Live2DAction): void {
    switch (action.type) {
      case 'expression':
        setExpression(action.name)
        break
      case 'motion':
        playMotion(action.group, action.index)
        break
      case 'param':
        setParam(action.name, action.value)
        break
      case 'sequence': {
        let delay = 0
        for (const sub of action.actions) {
          if (sub.type === 'wait') {
            delay += sub.ms
          } else {
            setTimeout(() => executeAction(sub), delay)
          }
        }
        break
      }
      case 'wait':
        break
    }
  }

  // ===== Socket Listeners =====

  function setupSocketListeners(): void {
    if (ownsSocketListeners) return

    const socket = getSocket()
    if (!socket) return

    ownsSocketListeners = true
    socketListenerOwners += 1
    if (listenerSocket) return

    listenerSocket = socket
    live2dActionListener = (data: unknown) => {
      executeAction(data as Live2DAction)
    }

    audioWithExpressionListener = (data: AudioWithExpressionEvent) => {
      if (!isCurrentChatTask(data)) return
      if (data.use_parameter_mapping && data.expressions?.frames) {
        playParameterTimeline({ ...data, expressions: data.expressions })
      } else {
        playAudio(data)
      }
    }

    audioStreamStartListener = (data: AudioStreamStartEvent) => {
      if (isCurrentChatTask(data)) startAudioStream(data)
    }
    audioStreamChunkListener = (data: AudioStreamChunkEvent) => {
      if (isCurrentChatTask(data)) pushAudioStreamChunk(data)
    }
    audioStreamEndListener = (data: AudioStreamEndEvent) => {
      if (isCurrentChatTask(data)) endAudioStream(data)
    }

    stopAudioListener = (data: ChatIdentity) => {
      if (!isCurrentChatTask(data)) return
      stopAudio()
    }
    disconnectListener = () => {
      stopAudio()
    }

    socket.on(Events.CHAT.LIVE2D_ACTION, live2dActionListener)
    socket.on(Events.CHAT.AUDIO_WITH_EXPRESSION, audioWithExpressionListener)
    socket.on(Events.CHAT.AUDIO_STREAM_START, audioStreamStartListener)
    socket.on(Events.CHAT.AUDIO_STREAM_CHUNK, audioStreamChunkListener)
    socket.on(Events.CHAT.AUDIO_STREAM_END, audioStreamEndListener)
    socket.on(Events.CHAT.STOP_AUDIO, stopAudioListener)
    socket.on('disconnect', disconnectListener)
  }

  function teardownSocketListeners(): void {
    if (!ownsSocketListeners) return

    ownsSocketListeners = false
    socketListenerOwners = Math.max(0, socketListenerOwners - 1)
    if (socketListenerOwners > 0 || !listenerSocket) return

    if (live2dActionListener) {
      listenerSocket.off(Events.CHAT.LIVE2D_ACTION, live2dActionListener)
    }
    if (audioWithExpressionListener) {
      listenerSocket.off(Events.CHAT.AUDIO_WITH_EXPRESSION, audioWithExpressionListener)
    }
    if (audioStreamStartListener) {
      listenerSocket.off(Events.CHAT.AUDIO_STREAM_START, audioStreamStartListener)
    }
    if (audioStreamChunkListener) {
      listenerSocket.off(Events.CHAT.AUDIO_STREAM_CHUNK, audioStreamChunkListener)
    }
    if (audioStreamEndListener) {
      listenerSocket.off(Events.CHAT.AUDIO_STREAM_END, audioStreamEndListener)
    }
    if (stopAudioListener) {
      listenerSocket.off(Events.CHAT.STOP_AUDIO, stopAudioListener)
    }
    if (disconnectListener) {
      listenerSocket.off('disconnect', disconnectListener)
    }

    listenerSocket = null
    live2dActionListener = null
    audioWithExpressionListener = null
    audioStreamStartListener = null
    audioStreamChunkListener = null
    audioStreamEndListener = null
    stopAudioListener = null
    disconnectListener = null
  }

  // ===== Destroy =====

  function destroy(): void {
    stopAudio()
    cancelTimeline()
    teardownSocketListeners()

    const app = getApp()
    if (app) {
      app.ticker.remove(tickLipSync)
      unloadModel()
    }
    destroyPixiApp()

    window.removeEventListener('resize', handleResize)
  }

  // ===== Lifecycle =====

  onMounted(() => {
    window.addEventListener('resize', handleResize)
  })

  onUnmounted(() => {
    destroy()
  })

  // ===== Public API (identical to original) =====

  return {
    isLoaded,
    isLoading,
    loadError,
    modelInfo,
    isDragging,
    init,
    loadModel,
    retryLoad,
    handleResize,
    setExpression,
    playMotion,
    setMouthTarget,
    executeAction,
    stopAudio,
    startDrag,
    onDrag,
    stopDrag,
    /** Scroll-wheel zoom. Positive delta = zoom in, negative = zoom out. Range 0.05x – 10x. */
    zoom(delta: number) {
      zoomFn(delta)
    },
    /** Reset to user's preferred initial position and scale */
    resetView() {
      resetViewFn()
    },
    setScaleStrategy(s: string) {
      setScaleStrategyFn(s)
    },
    /** Mouse focus (eye/head tracking) */
    focus(x: number, y: number) {
      focusFn(x, y)
    },
    destroy,
  }
}
