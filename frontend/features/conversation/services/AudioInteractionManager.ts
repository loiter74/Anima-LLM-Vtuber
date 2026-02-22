/**
 * AudioInteractionManager - True Singleton Manager
 *
 * Non-React singleton that manages ONE AudioInteractionService instance
 * and forwards events to external subscribers (e.g., Zustand stores).
 *
 * Architecture:
 * - Static getInstance() ensures only one manager exists
 * - Manager creates and owns the AudioInteractionService
 * - Emits typed events for state changes
 * - Zustand stores subscribe to these events
 */

import { logger } from '@/shared/utils/logger'
import { AudioRecorder } from '@/features/audio/services/AudioRecorder'
import { AudioInteractionService } from './AudioInteractionService'
import type { SocketService } from '@/features/connection/services/SocketService'

// ============================================================
// Manager Event Types
// ============================================================

export interface AudioInteractionManagerEvents {
  'recording:started': void
  'recording:stopped': void
  'recording:cancelled': void
  'recording:error': string
  'audio:playing': void
  'audio:stopped': void
  'manager:initialized': void
}

type EventListener<T> = (data: T) => void

// ============================================================
// AudioInteractionManager Class
// ============================================================

class AudioInteractionManager {
  // Singleton instance
  private static instance: AudioInteractionManager | null = null

  // Service and dependencies
  private service: AudioInteractionService | null = null
  private recorder: AudioRecorder | null = null
  private socket: SocketService | null = null

  // State
  private isInitialized: boolean = false

  // Event listeners
  private eventListeners: Map<keyof AudioInteractionManagerEvents, Set<EventListener<any>>> = new Map()

  // Private constructor for singleton
  private constructor() {
    logger.info('[AudioInteractionManager] Manager singleton created')
  }

  /**
   * Get the singleton instance
   */
  static getInstance(): AudioInteractionManager {
    if (!AudioInteractionManager.instance) {
      AudioInteractionManager.instance = new AudioInteractionManager()
    }
    return AudioInteractionManager.instance
  }

  /**
   * Initialize the manager with socket connection
   * This method is idempotent - can be called multiple times safely
   * @returns true if already initialized, false if this was the first initialization
   */
  initialize(socket: SocketService): boolean {
    if (this.isInitialized && this.socket === socket) {
      // Silent skip - already initialized with same socket
      return true
    }

    // Socket changed, recreate service
    if (this.isInitialized && this.socket !== socket) {
      logger.info('[AudioInteractionManager] Socket changed, recreating service')
      this.cleanup()
    }

    logger.info('[AudioInteractionManager] ========== Starting initialization ==========')

    // Create recorder (only once)
    if (!this.recorder) {
      logger.info('[AudioInteractionManager] Creating AudioRecorder')
      this.recorder = new AudioRecorder({ gain: 50.0 })
    }

    // Create service (only once)
    if (!this.service) {
      logger.info('[AudioInteractionManager] Creating AudioInteractionService')
      this.service = new AudioInteractionService(this.recorder)
      this.setupServiceEventForwarding()
    }

    // Set socket
    this.socket = socket
    this.service.setSocket(socket)

    this.isInitialized = true
    this.emit('manager:initialized')
    logger.info('[AudioInteractionManager] ========== Initialization complete ==========')

    return false
  }

  /**
   * Setup event forwarding from Service to Manager listeners
   * This ensures all Service events are forwarded to external subscribers
   */
  private setupServiceEventForwarding(): void {
    if (!this.service) {
      logger.error('[AudioInteractionManager] Cannot setup events - service is null')
      return
    }

    logger.info('[AudioInteractionManager] Setting up service event forwarding')

    // Forward all service events to manager listeners
    this.service.on('recording:started', () => {
      logger.info('[AudioInteractionManager] Forwarding: recording:started')
      this.emit('recording:started')
    })

    this.service.on('recording:stopped', () => {
      logger.info('[AudioInteractionManager] Forwarding: recording:stopped')
      this.emit('recording:stopped')
    })

    this.service.on('recording:cancelled', () => {
      logger.info('[AudioInteractionManager] Forwarding: recording:cancelled')
      this.emit('recording:cancelled')
    })

    this.service.on('recording:error', (error: string) => {
      logger.error('[AudioInteractionManager] Forwarding: recording:error:', error)
      this.emit('recording:error', error)
    })

    this.service.on('audio:playing', () => {
      logger.info('[AudioInteractionManager] Forwarding: audio:playing')
      this.emit('audio:playing')
    })

    this.service.on('audio:stopped', () => {
      logger.info('[AudioInteractionManager] Forwarding: audio:stopped')
      this.emit('audio:stopped')
    })

    logger.info('[AudioInteractionManager] Service event forwarding complete')
  }

  // ============================================================
  // Public API Methods (Proxy to Service)
  // ============================================================

  /**
   * Start recording
   */
  async startRecording(): Promise<void> {
    if (!this.service) {
      throw new Error('[AudioInteractionManager] Service not initialized')
    }
    logger.info('[AudioInteractionManager] startRecording called')
    await this.service.startRecording()
  }

  /**
   * Stop recording
   */
  stopRecording(): void {
    if (!this.service) {
      logger.warn('[AudioInteractionManager] Service not initialized')
      return
    }
    logger.info('[AudioInteractionManager] stopRecording called')
    this.service.stopRecording()
  }

  /**
   * Cancel recording
   */
  cancelRecording(): void {
    if (!this.service) {
      logger.warn('[AudioInteractionManager] Service not initialized')
      return
    }
    logger.info('[AudioInteractionManager] cancelRecording called')
    this.service.cancelRecording()
  }

  /**
   * Interrupt current audio/interaction
   */
  interrupt(): void {
    if (!this.service) {
      logger.warn('[AudioInteractionManager] Service not initialized')
      return
    }
    logger.info('[AudioInteractionManager] interrupt called')
    this.service.interrupt()
  }

  /**
   * Play audio
   */
  playAudio(base64: string, format: string = 'mp3'): void {
    if (!this.service) {
      logger.warn('[AudioInteractionManager] Service not initialized')
      return
    }
    logger.info('[AudioInteractionManager] playAudio called')
    this.service.playAudio(base64, format)
  }

  /**
   * Get recording state
   */
  getRecordingState(): 'idle' | 'recording' | 'error' {
    if (!this.service) {
      return 'error'
    }
    return this.service.getRecordingState()
  }

  /**
   * Check if manager is initialized
   */
  isInitialized(): boolean {
    return this.isInitialized && !!this.service
  }

  /**
   * Set current response text (for interrupt)
   */
  setCurrentResponse(text: string): void {
    if (!this.service) {
      logger.warn('[AudioInteractionManager] Service not initialized')
      return
    }
    this.service.setCurrentResponse(text)
  }

  // ============================================================
  // Event System for External Subscribers
  // ============================================================

  /**
   * Subscribe to an event
   * Returns an unsubscribe function
   */
  on<K extends keyof AudioInteractionManagerEvents>(
    event: K,
    listener: EventListener<AudioInteractionManagerEvents[K]>
  ): () => void {
    if (!this.eventListeners.has(event)) {
      this.eventListeners.set(event, new Set())
    }
    this.eventListeners.get(event)!.add(listener)

    logger.debug(`[AudioInteractionManager] Subscribed to event: ${event}`)

    // Return unsubscribe function
    return () => {
      const listeners = this.eventListeners.get(event)
      if (listeners) {
        listeners.delete(listener)
        logger.debug(`[AudioInteractionManager] Unsubscribed from event: ${event}`)
      }
    }
  }

  /**
   * Emit an event to all subscribers
   */
  private emit<K extends keyof AudioInteractionManagerEvents>(
    event: K,
    data?: AudioInteractionManagerEvents[K]
  ): void {
    const listeners = this.eventListeners.get(event)
    if (listeners) {
      listeners.forEach((listener) => {
        try {
          listener(data as any)
        } catch (error) {
          logger.error(`[AudioInteractionManager] Error in event listener for ${event}:`, error)
        }
      })
    }
  }

  /**
   * Remove all event listeners for a specific event or all events
   */
  removeAllListeners(event?: keyof AudioInteractionManagerEvents): void {
    if (event) {
      this.eventListeners.delete(event)
      logger.debug(`[AudioInteractionManager] Removed all listeners for event: ${event}`)
    } else {
      this.eventListeners.clear()
      logger.debug('[AudioInteractionManager] Removed all event listeners')
    }
  }

  // ============================================================
  // Cleanup
  // ============================================================

  /**
   * Cleanup resources
   */
  private cleanup(): void {
    logger.info('[AudioInteractionManager] Cleaning up resources')

    if (this.service) {
      this.service.destroy()
      this.service = null
    }

    this.recorder = null
    this.socket = null
    this.isInitialized = false

    logger.info('[AudioInteractionManager] Cleanup complete')
  }

  /**
   * Destroy the manager and cleanup resources
   * This should only be called when the app is shutting down
   */
  destroy(): void {
    logger.info('[AudioInteractionManager] Destroying manager')
    this.cleanup()
    this.removeAllListeners()
    AudioInteractionManager.instance = null
  }
}

// ============================================================
// Convenience getter function
// ============================================================

export function getAudioInteractionManager(): AudioInteractionManager {
  return AudioInteractionManager.getInstance()
}

// Export the class for type usage
export type { AudioInteractionManager }
