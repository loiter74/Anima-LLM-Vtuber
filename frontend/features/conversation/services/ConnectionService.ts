/**
 * ConnectionService - 连接状态管理
 * 只负责状态管理和事件监听
 */

import { EventService } from './EventService'
import type { SocketService } from '@/features/connection/services/SocketService'

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

export interface ConnectionState {
  status: ConnectionStatus
  error: string | null
}

export interface ConnectionServiceEvents {
  'status:change': ConnectionState
  'connected': void
  'disconnected': void
  'error': string
}

export class ConnectionService extends EventService<ConnectionServiceEvents> {
  private socket: SocketService | null = null
  private status: ConnectionStatus = 'disconnected'
  private error: string | null = null

  /** Get current state */
  getState(): ConnectionState {
    return {
      status: this.status,
      error: this.error,
    }
  }

  /** Check if connected */
  get isConnected(): boolean {
    return this.status === 'connected'
  }

  /** Set socket instance */
  setSocket(socket: SocketService): void {
    if (this.socket === socket) return

    this.socket = socket
    this.setupSocketHandlers()
  }

  /** Setup socket event handlers */
  private setupSocketHandlers(): void {
    if (!this.socket) return

    this.socket.on('connect', () => {
      this.updateStatus('connected')
      this.emit('connected')
    })

    this.socket.on('disconnect', () => {
      this.updateStatus('disconnected')
      this.emit('disconnected')
    })

    this.socket.on('connect_error', (error: Error) => {
      const errorMsg = `连接错误: ${error.message}`
      this.updateStatus('error', errorMsg)
      this.emit('error', errorMsg)
    })
  }

  /** Update connection status */
  private updateStatus(status: ConnectionStatus, error: string | null = null): void {
    this.status = status
    this.error = error

    this.emit('status:change', {
      status: this.status,
      error: this.error,
    })
  }

  /** Destroy service */
  override destroy(): void {
    this.removeAllListeners()
    this.socket = null
  }
}
