/**
 * VADProcessor Service
 * Handles Voice Activity Detection for audio streams
 */

import { logger } from '@/shared/utils/logger'

export class VADProcessor {
  private buffer: number[] = []
  private isSpeaking = false
  private silenceCounter = 0
  private speechCounter = 0

  private readonly threshold: number
  private readonly windowSize: number
  private readonly requiredSpeechHits: number
  private readonly requiredSilenceHits: number

  constructor(options?: {
    threshold?: number
    windowSize?: number
    requiredSpeechHits?: number
    requiredSilenceHits?: number
  }) {
    this.threshold = options?.threshold ?? 0.5
    this.windowSize = options?.windowSize ?? 512
    this.requiredSpeechHits = options?.requiredSpeechHits ?? 8
    this.requiredSilenceHits = options?.requiredSilenceHits ?? 20
  }

  /**
   * Process audio chunk and detect speech activity
   * Returns true when speech ends (silence detected after speech)
   */
  processChunk(audioChunk: number[]): boolean {
    // Calculate audio energy
    const energy = this.calculateEnergy(audioChunk)
    this.buffer.push(...audioChunk)

    // Speech detection logic
    if (energy > this.threshold) {
      this.speechCounter++
      this.silenceCounter = 0

      // Speech started
      if (this.speechCounter >= this.requiredSpeechHits && !this.isSpeaking) {
        this.isSpeaking = true
        logger.debug('[VADProcessor] Speech detected')
      }

      return false // Continue accumulating
    }

    // Energy below threshold
    if (this.isSpeaking) {
      this.silenceCounter++

      // Check for speech end
      if (this.silenceCounter >= this.requiredSilenceHits) {
        this.isSpeaking = false
        this.speechCounter = 0
        this.silenceCounter = 0
        const audio = this.flushBuffer()
        logger.debug('[VADProcessor] Speech ended')
        return true // Speech ended
      }
    }

    return false // Continue waiting
  }

  /**
   * Calculate audio energy (RMS)
   */
  private calculateEnergy(chunk: number[]): number {
    const sumSquares = chunk.reduce((sum, x) => sum + x * x, 0)
    return Math.sqrt(sumSquares / chunk.length)
  }

  /**
   * Flush the audio buffer
   */
  private flushBuffer(): number[] {
    const audio = [...this.buffer]
    this.buffer = []
    return audio
  }

  /**
   * Reset the processor state
   */
  reset(): void {
    this.buffer = []
    this.isSpeaking = false
    this.silenceCounter = 0
    this.speechCounter = 0
  }

  /**
   * Get current buffer
   */
  getBuffer(): number[] {
    return [...this.buffer]
  }

  /**
   * Clear buffer
   */
  clearBuffer(): void {
    this.buffer = []
  }

  /**
   * Check if currently detecting speech
   */
  get speaking(): boolean {
    return this.isSpeaking
  }
}
