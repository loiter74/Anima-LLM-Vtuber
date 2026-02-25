/**
 * AudioInteractionService - 音频交互服务
 * 处理录音和 TTS 音频播放
 *
 * 职责：
 * - 麦克风录音控制
 * - TTS 音频播放
 * - 音频中断处理
 * - 录音状态管理
 */

import { logger } from '@/shared/utils/logger'
import { EventService } from './EventService'
import { AudioRecorder } from '@/features/audio/services/AudioRecorder'
import { AudioPlayer } from '@/features/audio/services/AudioPlayer'
import type { SocketService } from '@/features/connection/services/SocketService'

export type RecordingStatus = 'idle' | 'recording' | 'error'

export interface AudioInteractionServiceEvents {
  'recording:started': void
  'recording:stopped': void
  'recording:cancelled': void
  'recording:error': string
  'audio:playing': void
  'audio:stopped': void
}

export class AudioInteractionService extends EventService<AudioInteractionServiceEvents> {
  private socket: SocketService | null = null
  private recorder: AudioRecorder | null = null
  private isRecording: boolean = false
  private currentResponse: string = ''
  private startRecordingCallCount: number = 0  // 添加调用计数器

  constructor(recorder?: AudioRecorder) {
    super()
    // 如果提供了 recorder 实例则使用，否则稍后设置
    if (recorder) {
      this.recorder = recorder
    }
  }

  /**
   * 设置 Socket 实例
   */
  setSocket(socket: SocketService): void {
    this.socket = socket
  }

  /**
   * 设置录音器实例
   */
  setRecorder(recorder: AudioRecorder): void {
    this.recorder = recorder
  }

  /**
   * 设置当前响应文本（用于中断时发送）
   */
  setCurrentResponse(text: string): void {
    this.currentResponse = text
  }

  /**
   * 获取录音状态
   */
  getRecordingState(): RecordingStatus {
    if (!this.recorder) return 'error'
    return this.isRecording ? 'recording' : 'idle'
  }

  /**
   * 开始录音
   */
  async startRecording(): Promise<void> {
    this.startRecordingCallCount++
    const callId = this.startRecordingCallCount
    logger.info(`[AudioInteractionService] 📞 startRecording called (call #${callId})`)

    logger.info('[AudioInteractionService] 📞 startRecording 开始')
    logger.info('[AudioInteractionService] socket:', !!this.socket, 'connected:', this.socket?.connected)
    logger.info('[AudioInteractionService] recorder:', !!this.recorder)

    if (!this.socket?.connected) {
      const error = '未连接到服务器'
      logger.error('[AudioInteractionService]', error)
      this.emit('recording:error', error)
      throw new Error(error)
    }

    if (!this.recorder) {
      const error = '录音器未初始化'
      logger.error('[AudioInteractionService]', error)
      this.emit('recording:error', error)
      throw new Error(error)
    }

    logger.info('[AudioInteractionService] 开始录音，中断当前语音')

    // 停止当前播放
    logger.info(`[AudioInteractionService] 🛑 Stopping global audio (call #${callId})`)
    AudioPlayer.stopGlobalAudio()
    logger.info(`[AudioInteractionService] ✅ Audio stopped (call #${callId})`)

    // 发送中断信号
    logger.info(`[AudioInteractionService] 📤 About to send interrupt_signal (call #${callId})`)
    logger.info(`[AudioInteractionService] socket instance: ${!!this.socket}, connected: ${this.socket?.connected}`)
    logger.info(`[AudioInteractionService] currentResponse text: "${this.currentResponse}"`)

    this.socket.emit('interrupt_signal', {
      text: this.currentResponse,
    })

    logger.info(`[AudioInteractionService] ✅ interrupt_signal sent (call #${callId})`)

    // 清空当前响应
    this.currentResponse = ''

    try {
      logger.info('[AudioInteractionService] 调用 recorder.start()')

      // Emit recording:starting event before calling recorder.start()
      this.emit('recording:starting' as any)
      logger.info('[AudioInteractionService] 📢 Emitted recording:starting event')

      // Capture socket reference to check later
      const socketRef = this.socket

      await this.recorder.start((pcmData) => {
        // Check socket connection before emitting
        if (!socketRef?.connected) {
          logger.warn('[AudioInteractionService] Socket disconnected during recording, skipping chunk')
          return
        }

        // 发送音频数据
        socketRef.emit('raw_audio_data', {
          audio: Array.from(pcmData),
        })

        // 触发自定义事件（用于 UI 反馈）
        window.dispatchEvent(new CustomEvent('audio-chunk-sent'))
      })

      this.isRecording = true
      logger.info('[AudioInteractionService] About to emit recording:started event')
      this.emit('recording:started')
      logger.info('[AudioInteractionService] ✅ recording:started event emitted')

      // 通知录音状态变更
      ;(window as any).__isRecording = true
      window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: true }))

      logger.info('[AudioInteractionService] ✅ 录音已启动')
    } catch (err) {
      logger.warn('[AudioInteractionService] ⚠️ 录音启动失败:', err)
      const errorMessage = err instanceof Error ? err.message : '无法访问麦克风'
      this.emit('recording:error', errorMessage)
      throw err
    }
  }

  /**
   * 停止录音并发送到后端处理
   */
  stopRecording(): void {
    if (!this.recorder) {
      logger.warn('[AudioInteractionService] 录音器未初始化')
      return
    }

    if (!this.isRecording) {
      logger.debug('[AudioInteractionService] 当前未在录音')
      return
    }

    logger.debug('[AudioInteractionService] 停止录音')

    // 停止录音
    this.recorder.stop()

    this.isRecording = false
    this.emit('recording:stopped')

    // 通知服务器录音结束
    if (this.socket?.connected) {
      this.socket.emit('mic_audio_end', { from_name: 'User' })
    }

    // 通知录音状态变更
    ;(window as any).__isRecording = false
    window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: false }))
  }

  /**
   * 取消录音（不发送到后端，直接返回idle状态）
   */
  cancelRecording(): void {
    if (!this.recorder) {
      logger.warn('[AudioInteractionService] 录音器未初始化')
      return
    }

    if (!this.isRecording) {
      logger.debug('[AudioInteractionService] 当前未在录音')
      return
    }

    logger.debug('[AudioInteractionService] 取消录音，不发送到后端')

    // 停止录音
    this.recorder.stop()

    this.isRecording = false
    this.emit('recording:stopped')
    this.emit('recording:cancelled')  // 新增：取消事件

    // 通知录音状态变更
    ;(window as any).__isRecording = false
    window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: false }))
  }

  /**
   * 播放音频
   */
  async playAudio(base64: string, format: string = 'mp3'): Promise<void> {
    logger.info('[AudioInteractionService] 🎵 收到新音频播放请求')

    // 先停止当前播放（如果有）
    if (AudioPlayer.isPlaying) {
      logger.info('[AudioInteractionService] 🛑 检测到正在播放，先停止旧音频')
      AudioPlayer.stopGlobalAudio()
      this.emit('audio:stopped')

      // 等待一小段时间确保停止完成
      await new Promise(resolve => setTimeout(resolve, 50))
      logger.info('[AudioInteractionService] ✅ 旧音频已停止，准备播放新音频')
    }

    this.emit('audio:playing')

    try {
      await AudioPlayer.playGlobal(base64, format)
      logger.info('[AudioInteractionService] ✅ 音频播放已启动')
    } catch (error) {
      logger.error('[AudioInteractionService] ❌ 音频播放失败:', error)
      this.emit('audio:stopped')
      throw error
    }
  }

  /**
   * 中断
   */
  interrupt(): void {
    logger.debug('[AudioInteractionService] 打断对话')

    // 停止音频播放
    AudioPlayer.stopGlobalAudio()

    // 发送中断信号
    if (this.socket?.connected) {
      this.socket.emit('interrupt_signal', {
        text: this.currentResponse,
      })
    }

    // 清空当前响应
    this.currentResponse = ''

    this.emit('audio:stopped')
  }

  /**
   * 销毁服务
   */
  override destroy(): void {
    logger.debug('[AudioInteractionService] 销毁服务')

    // 停止录音
    if (this.isRecording) {
      this.stopRecording()
    }

    // 停止音频播放
    AudioPlayer.stopGlobalAudio()

    this.removeAllListeners()
    this.socket = null
    this.recorder = null
  }
}
