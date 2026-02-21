/**
 * AudioRecorder Service
 * Handles microphone recording and audio data capture
 */

import { logger } from '@/shared/utils/logger'
import { float32ToInt16 } from '@/lib/utils/audio'
import type { AudioRecorderOptions, AudioDataCallback } from '@/shared/types/audio'

export class AudioRecorder {
  private audioContext: AudioContext | null = null
  private mediaStream: MediaStream | null = null
  private processor: ScriptProcessorNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private isRecording: boolean = false
  private audioChunkCount: number = 0
  private lastLogTime: number = 0

  private options: Required<AudioRecorderOptions>
  private onAudioDataCallback: AudioDataCallback | null = null

  constructor(options: AudioRecorderOptions = {}) {
    this.options = {
      sampleRate: 16000,
      channelCount: 1,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
      gain: 50.0,
      ...options,
    }
  }

  /**
   * Check microphone permission status
   */
  private async checkPermission(): Promise<boolean> {
    if (!navigator.permissions) {
      return true // Browser doesn't support permission query
    }

    try {
      const permissionStatus = await navigator.permissions.query({
        name: 'microphone' as PermissionName,
      })
      if (permissionStatus.state === 'denied') {
        throw new Error(
          '麦克风权限被拒绝。请在浏览器地址栏点击锁图标，允许麦克风访问后刷新页面。'
        )
      }
      return true
    } catch (err) {
      // Some browsers don't support querying microphone permission
      logger.debug('[AudioRecorder] 无法查询麦克风权限状态:', err)
      return true
    }
  }

  /**
   * Start recording audio
   */
  async start(onAudioData: AudioDataCallback): Promise<void> {
    if (this.isRecording) {
      logger.warn('[AudioRecorder] 录音已在进行中')
      return
    }

    await this.checkPermission()
    this.onAudioDataCallback = onAudioData

    try {
      // Get media stream
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: this.options.sampleRate,
          channelCount: this.options.channelCount,
          echoCancellation: this.options.echoCancellation,
          noiseSuppression: this.options.noiseSuppression,
          autoGainControl: this.options.autoGainControl,
        },
      })

      // Create audio context
      this.audioContext = new AudioContext({
        sampleRate: this.options.sampleRate,
      })
      this.source = this.audioContext.createMediaStreamSource(this.mediaStream)
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1)

      // Connect nodes
      const silentDestination = this.audioContext.createMediaStreamDestination()
      this.source.connect(this.processor)
      this.processor.connect(silentDestination)

      // Reset counters
      this.audioChunkCount = 0
      this.lastLogTime = Date.now()

      // Set up audio processing
      this.processor.onaudioprocess = (event) => {
        this.handleAudioProcess(event)
      }

      this.isRecording = true
      logger.debug('[AudioRecorder] ✅ 录音已启动')
    } catch (err) {
      this.cleanup()
      throw this.normalizeError(err)
    }
  }

  /**
   * Handle audio processing
   */
  private handleAudioProcess(event: AudioProcessingEvent): void {
    this.audioChunkCount++
    const now = Date.now()

    // Log heartbeat every 5 seconds
    if (now - this.lastLogTime > 5000) {
      this.lastLogTime = now
    }

    const inputData = event.inputBuffer.getChannelData(0)

    // Convert to Int16 PCM with gain
    const pcmData = float32ToInt16(
      applyGainToData(inputData, this.options.gain)
    )

    // Log stats every 10 chunks
    if (this.audioChunkCount % 10 === 1) {
      const min = Math.min(...Array.from(pcmData))
      const max = Math.max(...Array.from(pcmData))
      const mean = pcmData.reduce((sum, v) => sum + Math.abs(v), 0) / pcmData.length
      console.log(
        `[AudioRecorder] 📊 PCM #${this.audioChunkCount}: range=[${min.toFixed(0)}, ${max.toFixed(0)}], mean=${mean.toFixed(2)}, gain=${this.options.gain}x`
      )
    }

    // Send audio data via callback
    if (this.onAudioDataCallback) {
      this.onAudioDataCallback(pcmData)
    }
  }

  /**
   * Stop recording
   */
  stop(): void {
    if (!this.isRecording) {
      return
    }

    this.cleanup()
    logger.debug('[AudioRecorder] ✅ 录音已停止')
  }

  /**
   * Clean up resources
   */
  private cleanup(): void {
    this.isRecording = false

    // Stop media stream
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop())
      this.mediaStream = null
    }

    // Disconnect processor
    if (this.processor) {
      this.processor.disconnect()
      this.processor = null
    }

    // Close audio context
    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }

    this.source = null
  }

  /**
   * Normalize error to user-friendly message
   */
  private normalizeError(err: unknown): Error {
    if (err instanceof DOMException) {
      if (err.name === 'NotAllowedError') {
        return new Error(
          '麦克风权限被拒绝。请点击浏览器地址栏的锁图标，允许' +
            (window.location.protocol === 'https:' ? '' : '在 https 或 localhost 环境下') +
            '麦克风访问权限。'
        )
      } else if (err.name === 'NotFoundError') {
        return new Error('未检测到麦克风设备。请连接麦克风后重试。')
      }
    }

    if (
      window.location.protocol !== 'https:' &&
      window.location.hostname !== 'localhost'
    ) {
      return new Error('浏览器安全限制：麦克风权限需要 HTTPS 或 localhost 环境。')
    }

    return new Error('无法访问麦克风')
  }

  /**
   * Check if currently recording
   */
  get recording(): boolean {
    return this.isRecording
  }
}

/**
 * Helper function to apply gain to Float32Array
 */
function applyGainToData(data: Float32Array, gain: number): Float32Array {
  const result = new Float32Array(data.length)
  for (let i = 0; i < data.length; i++) {
    let s = data[i] * gain
    result[i] = Math.max(-1, Math.min(1, s))
  }
  return result
}
