/**
 * useAudioInteraction Hook
 *
 * Simplified hook that proxies to AudioInteractionManager singleton.
 *
 * Architecture:
 * - Hook is a thin wrapper around the manager
 * - Manager is the true singleton (non-React)
 * - Store subscribes to manager events
 * - Components just read store state and call hook methods
 */

import { useEffect, useCallback, useRef } from 'react'
import { logger } from '@/shared/utils/logger'
import { getAudioInteractionManager } from '@/features/conversation/services/AudioInteractionManager'
import { setupAudioStoreManagerSubscription } from '@/shared/state/stores/audioStore'
import { useAudioStore } from '@/shared/state/stores/audioStore'
import type { SocketService } from '@/features/connection/services/SocketService'
import type { UseAudioInteractionOptions, UseAudioInteractionReturn } from './types'

// Module-level flag to ensure initialization happens only once across all hook instances
let globalInitFlag = false

// ============================================================
// Hook Implementation
// ============================================================

export function useAudioInteraction(
  socket: SocketService | null,
  options: UseAudioInteractionOptions = {}
): UseAudioInteractionReturn {
  const { onStatusChange, onError } = options

  // Track if this hook instance has logged initialization
  const hasLoggedInit = useRef(false)

  // Initialize manager and setup store subscription
  useEffect(() => {
    // 🆕 Always get manager instance (even without socket)
    const manager = getAudioInteractionManager()

    // Only initialize if socket is available
    if (socket) {
      // Initialize manager with socket (idempotent)
      const wasAlreadyInitialized = manager.initialize(socket)

      // Setup store subscription to manager events (idempotent)
      setupAudioStoreManagerSubscription()

      // Only log on first actual initialization
      if (!hasLoggedInit.current && !wasAlreadyInitialized) {
        logger.info('[useAudioInteraction] ========== Starting initialization ==========')
        hasLoggedInit.current = true
        logger.info('[useAudioInteraction] ========== Initialization complete ==========')
      } else if (!hasLoggedInit.current) {
        // Manager was already initialized by another component
        logger.debug('[useAudioInteraction] Using existing manager instance')
        hasLoggedInit.current = true
      }
    } else {
      logger.debug('[useAudioInteraction] Socket not ready, manager will be initialized when socket connects')
    }

    // Cleanup on unmount
    return () => {
      logger.debug('[useAudioInteraction] Component unmounted (manager persists)')
    }
  }, [socket])

  // Optional: Handle status change callbacks
  // Note: This is just for backward compatibility with existing callbacks
  // The real state management happens in the store via manager events
  useEffect(() => {
    if (!onStatusChange && !onError) return

    const manager = getAudioInteractionManager()

    const unsubscribes: (() => void)[] = []

    // Subscribe to events for callbacks only (state is managed by store)
    if (onStatusChange) {
      unsubscribes.push(
        manager.on('recording:started', () => onStatusChange('listening')),
        manager.on('recording:stopped', () => onStatusChange('processing')),
        manager.on('recording:cancelled', () => onStatusChange('idle')),
        manager.on('audio:playing', () => onStatusChange('speaking')),
        manager.on('audio:stopped', () => onStatusChange('idle'))
      )
    }

    if (onError) {
      unsubscribes.push(
        manager.on('recording:error', (error: string) => onError(error))
      )
    }

    return () => {
      unsubscribes.forEach((unsub) => unsub())
    }
  }, [onStatusChange, onError])

  // ============================================================
  // Methods - Simple proxies to manager
  // ============================================================

  const startRecording = useCallback(async () => {
    const manager = getAudioInteractionManager()
    logger.info('[useAudioInteraction] 📞 startRecording called')

    // 🆕 检查服务是否已初始化（直接访问属性，避免方法调用问题）
    // @ts-ignore - 访问私有属性
    if (!manager.isInitialized || !manager.service) {
      const error = '服务未初始化，请先连接到服务器'
      logger.error('[useAudioInteraction]', error)
      onError?.(error)
      throw new Error(error)
    }

    await manager.startRecording()
  }, [onError])

  const stopRecording = useCallback(() => {
    const manager = getAudioInteractionManager()
    logger.info('[useAudioInteraction] ⏹ stopRecording called')
    manager.stopRecording()
  }, [])

  const cancelRecording = useCallback(() => {
    const manager = getAudioInteractionManager()
    logger.info('[useAudioInteraction] ❌ cancelRecording called')
    manager.cancelRecording()
  }, [])

  const interrupt = useCallback(() => {
    const manager = getAudioInteractionManager()
    logger.info('[useAudioInteraction] 🛑 interrupt called')
    manager.interrupt()
  }, [])

  const playAudio = useCallback((base64: string, format = 'mp3') => {
    const manager = getAudioInteractionManager()
    manager.playAudio(base64, format)
  }, [])

  // Get recording state from store (source of truth)
  const isRecording = useAudioStore((state) => state.isRecording)

  return {
    isRecording,
    startRecording,
    stopRecording,
    cancelRecording,
    interrupt,
    playAudio,
  }
}

// ============================================================
// Exported Utilities
// ============================================================

/**
 * Get the manager instance (for direct access if needed)
 */
export function getAudioInteractionManagerForTesting() {
  return getAudioInteractionManager()
}

/**
 * Cleanup manager (for testing only)
 * WARNING: This destroys the singleton, don't use in production
 */
export function cleanupAudioInteractionManagerForTesting(): void {
  const manager = getAudioInteractionManager()
  manager.destroy()
}
