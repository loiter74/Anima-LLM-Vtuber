/**
 * ConversationService - 会话服务
 * 组合所有子服务，提供统一的业务 API
 *
 * 职责：
 * - 组合 ConnectionService, MessagingService, AudioInteractionService
 * - 处理 Socket 事件路由
 * - 管理会话状态（status, messages, currentResponse）
 * - 提供统一的业务 API
 */

import { logger } from '@/shared/utils/logger'
import { EventService } from './EventService'
import { ConnectionService, ConnectionState } from './ConnectionService'
import { MessagingService } from './MessagingService'
import { AudioInteractionService } from './AudioInteractionService'
import { useConversationStore } from '../stores/conversationStore'
import type { SocketService } from '@/features/connection/services/SocketService'
import type { Message } from '../types'
import { CONTROL_SIGNALS } from '@/features/connection/constants/events'

export type ConversationStatus = 'idle' | 'listening' | 'processing' | 'speaking' | 'interrupted' | 'error'

export interface ConversationServiceEvents {
  'status:change': ConversationStatus
  'message:appended': Message
  'response:appended': string
  'response:finished': void
  'error': string
  'expression': string
}

export class ConversationService extends EventService<ConversationServiceEvents> {
  // Singleton instance
  private static instance: ConversationService | null = null

  private connectionService: ConnectionService
  private messagingService: MessagingService
  private audioService: AudioInteractionService
  private socket: SocketService | null = null
  private conversationStore = useConversationStore
  private lastProcessedSeq: number = -1
  private isInitialized: boolean = false

  // Private constructor for singleton
  private constructor() {
    super()

    // 创建子服务
    this.connectionService = new ConnectionService(true) // 自动重连
    this.messagingService = new MessagingService()
    this.audioService = new AudioInteractionService()

    // 设置子服务之间的通信
    this.setupServiceIntegration()
  }

  /**
   * Get the singleton instance
   */
  static getInstance(): ConversationService {
    if (!ConversationService.instance) {
      ConversationService.instance = new ConversationService()
      logger.info('[ConversationService] ✅ Singleton instance created')
    }
    return ConversationService.instance
  }

  /**
   * Initialize the service (idempotent)
   */
  initialize(socket: SocketService): void {
    if (this.isInitialized && this.socket === socket) {
      logger.debug('[ConversationService] Already initialized with same socket')
      return
    }

    // Socket changed, cleanup and reinitialize
    if (this.isInitialized && this.socket !== socket) {
      logger.info('[ConversationService] Socket changed, reinitializing')
      this.cleanupSocketEventHandlers()
    }

    logger.debug('[ConversationService] 初始化服务')

    this.socket = socket

    // 设置 Socket 到所有子服务
    this.connectionService.setSocket(socket)
    this.messagingService.setSocket(socket)
    this.audioService.setSocket(socket)

    // 设置 Socket 事件处理器（只注册一次）
    if (!this.isInitialized || this.socket !== socket) {
      this.setupSocketEventHandlers()
      this.isInitialized = true
    }
  }

  /**
   * 设置服务之间的集成
   */
  private setupServiceIntegration(): void {
    // 连接状态变化
    this.connectionService.on('status:change', (state: ConnectionState) => {
      if (state.status === 'error' && state.error) {
        this.emit('error', state.error)
      }
    })

    // 消息已发送 - 添加到 store
    this.messagingService.on('message:sent', (message: Message) => {
      logger.info(`[ConversationService] 📨 收到 message:sent 事件 - ${message.text}`)
      this.conversationStore.getState().addMessage('user', message.text)
      logger.info(`[ConversationService] ✅ 用户消息已添加到 store，当前消息数: ${this.conversationStore.getState().messages.length}`)
    })

    // 响应开始
    this.messagingService.on('response:start', () => {
      this.updateStatus('processing')
    })

    // 响应超时
    this.messagingService.on('response:timeout', () => {
      this.conversationStore.getState().setStatus('idle')
      this.conversationStore.getState().setError('响应超时，请重试')
      this.conversationStore.getState().setTyping(false)
    })

    // 录音开始
    this.audioService.on('recording:started', () => {
      this.updateStatus('listening')
    })

    // 录音停止
    this.audioService.on('recording:stopped', () => {
      if (this.socket?.connected) {
        this.updateStatus('processing')
      } else {
        this.updateStatus('idle')
      }
    })

    // 录音错误
    this.audioService.on('recording:error', (error: string) => {
      this.conversationStore.getState().setError(error)
      this.emit('error', error)
    })

    // 音频播放开始
    this.audioService.on('audio:playing', () => {
      this.updateStatus('speaking')
    })

    // 音频停止
    this.audioService.on('audio:stopped', () => {
      this.updateStatus('idle')
    })
  }

  /**
   * 设置 Socket 事件处理器
   */
  private setupSocketEventHandlers(): void {
    if (!this.socket) return

    // 🆕 先移除旧的监听器，避免重复注册
    this.socket.off('text')
    this.socket.off('audio')
    this.socket.off('transcript')
    this.socket.off('control')
    this.socket.off('error')
    this.socket.off('expression')

    logger.info('[ConversationService] ✅ 清理旧的 Socket 监听器')

    const state = this.conversationStore.getState()

    // Text events (streaming response)
    this.socket.on('text', (data: { text: string; type: string; seq: number }) => {
      logger.debug(`[ConversationService] 收到文本事件 - seq: ${data.seq}, 长度: ${data.text.length}`)

      if (data.text === '') {
        // Completion marker
        if (data.seq === this.lastProcessedSeq) {
          logger.debug(`[ConversationService] 跳过重复的完成标记 seq=${data.seq}`)
          return
        }

        logger.debug(`[ConversationService] 检测到完成标记 seq=${data.seq}`)
        this.lastProcessedSeq = data.seq
        state.finishResponse()
        this.emit('response:finished')
      } else {
        state.appendToResponse(data.text)
        this.emit('response:appended', data.text)
      }
    })

    // Audio events (TTS)
    this.socket.on('audio', (data: { audio_data?: string; audio_url?: string; format?: string }) => {
      const dataLength = data.audio_data?.length || 0

      logger.debug('[ConversationService] 收到音频事件')
      logger.debug(`[ConversationService] 音频数据长度: ${dataLength}`)
      logger.debug(`[ConversationService] 音频格式: ${data.format || '未指定'}`)

      if (data.audio_data && data.audio_data.trim().length > 0) {
        if (dataLength < 100) {
          logger.warn('[ConversationService] 音频数据太短，可能无效:', dataLength)
        }

        const cleanBase64 = data.audio_data.trim()
        this.audioService.playAudio(cleanBase64, data.format || 'mp3')
      } else if (data.audio_url) {
        logger.debug('[ConversationService] 收到音频 URL:', data.audio_url)
      } else {
        logger.warn('[ConversationService] 收到空音频事件，忽略')
      }
    })

    // Transcript events (ASR results)
    this.socket.on('transcript', (data: { text: string; is_final?: boolean }) => {
      logger.debug(`[ConversationService] 收到转录: ${data.text}, is_final: ${data.is_final}`)

      if (data.is_final && data.text) {
        state.addMessage('user', data.text)
        this.emit('message:appended', {
          id: `transcript_${Date.now()}`,
          sender: 'user',
          text: data.text,
          time: new Date().toISOString(),
        })
      }
    })

    // Control events
    this.socket.on('control', (data: { text: string }) => {
      logger.debug(`[ConversationService] 控制信号: ${data.text}`)

      switch (data.text) {
        case CONTROL_SIGNALS.START_MIC:
          this.updateStatus('listening')
          break
        case CONTROL_SIGNALS.INTERRUPT:
          // Only interrupt on INTERRUPT signal, not INTERRUPTED
          // INTERRUPTED is a response to our interrupt_signal, don't send another one
          this.audioService.interrupt()
          break
        case CONTROL_SIGNALS.INTERRUPTED:
          // Backend confirmed the interrupt, just update status locally
          // Don't call audioService.interrupt() to avoid loop
          this.updateStatus('idle')
          break
        case CONTROL_SIGNALS.MIC_AUDIO_END:
          this.updateStatus('processing')
          break
        case CONTROL_SIGNALS.NO_AUDIO_DATA:
          this.updateStatus('idle')
          break
        case CONTROL_SIGNALS.CONVERSATION_START:
          this.updateStatus('processing')
          break
        case CONTROL_SIGNALS.CONVERSATION_END:
          this.updateStatus('idle')
          break
      }
    })

    // Error events
    this.socket.on('error', (data: { message: string }) => {
      // 🆕 处理"处理被中断"错误（正常打断行为，不是真正的错误）
      if (data.message === '处理被中断' || data.message.includes('interrupt')) {
        logger.info(`[ConversationService] ✅ 对话被正常中断: ${data.message}`)
        // 不设置为错误状态，直接返回 idle
        this.updateStatus('idle')
        return
      }

      // 其他错误正常处理
      logger.error(`[ConversationService] 错误事件: ${data.message}`)
      state.setError(data.message)
      state.setStatus('error')
      this.emit('error', data.message)
    })

    // Expression events (Live2D)
    this.socket.on('expression', (data: { expression: string; timestamp?: number }) => {
      logger.debug(`[ConversationService] 表情事件: ${data.expression}`)
      this.emit('expression', data.expression)
    })
  }

  /**
   * 更新会话状态
   */
  private updateStatus(status: ConversationStatus): void {
    this.conversationStore.getState().setStatus(status)
    this.emit('status:change', status)
  }

  // ============ Public API ============

  /**
   * 连接
   */
  connect(): void {
    this.connectionService.connect()
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    this.connectionService.disconnect()
  }

  /**
   * 发送文本消息
   */
  sendText(text: string): void {
    this.messagingService.sendText(text)
  }

  /**
   * 开始录音
   */
  async startRecording(): Promise<void> {
    await this.audioService.startRecording()
  }

  /**
   * 停止录音
   */
  stopRecording(): void {
    this.audioService.stopRecording()
  }

  /**
   * 中断
   */
  interrupt(): void {
    this.audioService.interrupt()
  }

  /**
   * 清空历史记录
   */
  clearHistory(): void {
    this.messagingService.clearHistory()
    this.conversationStore.getState().clearMessages()
  }

  /**
   * 获取连接状态
   */
  getConnectionState(): ConnectionState {
    return this.connectionService.getState()
  }

  /**
   * 是否已连接
   */
  get isConnected(): boolean {
    return this.connectionService.isConnected
  }

  /**
   * 设置当前响应文本
   */
  setCurrentResponse(text: string): void {
    this.audioService.setCurrentResponse(text)
  }

  /**
   * 清理 Socket 事件处理器
   */
  private cleanupSocketEventHandlers(): void {
    if (!this.socket) return

    logger.debug('[ConversationService] 清理 Socket 事件处理器')

    this.socket.off('text')
    this.socket.off('audio')
    this.socket.off('transcript')
    this.socket.off('control')
    this.socket.off('error')
    this.socket.off('expression')
  }

  /**
   * 销毁服务
   */
  override destroy(): void {
    logger.debug('[ConversationService] 销毁服务')

    // 销毁子服务
    this.connectionService.destroy()
    this.messagingService.destroy()
    this.audioService.destroy()

    // 清理 Socket 事件监听
    this.cleanupSocketEventHandlers()

    this.removeAllListeners()
    this.socket = null
    this.isInitialized = false
  }
}

// ============================================================
// Convenience getter function
// ============================================================

/**
 * Get the ConversationService singleton instance
 */
export function getConversationService(): ConversationService {
  return ConversationService.getInstance()
}
