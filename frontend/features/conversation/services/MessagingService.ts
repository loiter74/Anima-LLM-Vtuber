/**
 * MessagingService - 消息发送服务
 * 处理文本消息发送和响应超时
 *
 * 职责：
 * - 发送文本消息
 * - 响应超时处理
 * - 消息历史管理
 */

import { logger } from '@/shared/utils/logger'
import { EventService } from './EventService'
import { AudioPlayer } from '@/features/audio/services/AudioPlayer'
import type { SocketService } from '@/features/connection/services/SocketService'
import type { Message } from '../types'

export interface MessagingServiceEvents {
  'message:sent': Message
  'response:start': void
  'response:timeout': void
  'history:cleared': void
}

export class MessagingService extends EventService<MessagingServiceEvents> {
  private socket: SocketService | null = null
  private responseTimeoutMs: number = 120000 // 120秒（2分钟）
  private timeoutId: ReturnType<typeof setTimeout> | null = null

  /**
   * 设置 Socket 实例
   */
  setSocket(socket: SocketService): void {
    this.socket = socket
  }

  /**
   * 发送文本消息
   */
  sendText(text: string, fromName: string = 'User'): void {
    if (!this.socket?.connected) {
      logger.warn('[MessagingService] Socket 未连接，无法发送消息')
      return
    }

    logger.debug(`[MessagingService] 发送消息: ${text.substring(0, 50)}...`)

    // 中断当前语音播放
    AudioPlayer.stopGlobalAudio()

    // 创建用户消息
    const message: Message = {
      id: this.generateMessageId(),
      sender: 'user',
      text,
      time: new Date().toISOString(),
    }

    // 发射消息已发送事件
    this.emit('message:sent', message)

    // 发射响应开始事件
    this.emit('response:start')

    // 发送消息到服务器
    this.socket.emit('text_input', {
      text,
      from_name: fromName,
    })

    // 设置响应超时
    this.startResponseTimeout()
  }

  /**
   * 清空历史记录
   */
  clearHistory(): void {
    logger.debug('[MessagingService] 清空历史记录')

    if (this.socket?.connected) {
      this.socket.emit('clear_history')
    }

    this.emit('history:cleared')
  }

  /**
   * 开始响应超时计时
   */
  private startResponseTimeout(): void {
    // 清除之前的超时
    this.clearResponseTimeout()

    this.timeoutId = setTimeout(() => {
      logger.debug('[MessagingService] 响应超时（2分钟）')
      this.emit('response:timeout')
    }, this.responseTimeoutMs)
  }

  /**
   * 清除响应超时
   */
  clearResponseTimeout(): void {
    if (this.timeoutId) {
      clearTimeout(this.timeoutId)
      this.timeoutId = null
    }
  }

  /**
   * 设置响应超时时间
   */
  setResponseTimeout(ms: number): void {
    this.responseTimeoutMs = ms
  }

  /**
   * 生成消息 ID
   */
  private generateMessageId(): string {
    return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  /**
   * 销毁服务
   */
  override destroy(): void {
    logger.debug('[MessagingService] 销毁服务')
    this.clearResponseTimeout()
    this.removeAllListeners()
    this.socket = null
  }
}
