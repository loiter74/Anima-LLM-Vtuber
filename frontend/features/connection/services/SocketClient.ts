/**
 * SocketClient
 * socket.io-client 包装器（全局单例）
 */

import { io, Socket } from 'socket.io-client'
import type { SocketEvents, SocketEmits } from '../types'
import { DEFAULT_SERVER_URL } from '../constants/config'

// 全局单例 socket
let globalSocket: Socket | null = null
let globalSocketUrl: string | null = null

export class SocketClient {
  private socket: Socket | null = null
  private url: string

  constructor(url: string = DEFAULT_SERVER_URL) {
    this.url = url
    // 复用全局 socket
    if (globalSocket && globalSocketUrl === url) {
      this.socket = globalSocket
    }
  }

  /**
   * Connect to the server
   */
  connect(): Promise<void> {
    // 如果已经连接，直接返回
    if (this.socket?.connected) {
      return Promise.resolve()
    }

    // 如果有全局 socket，等待连接完成
    if (globalSocket && globalSocketUrl === this.url) {
      this.socket = globalSocket

      if (this.socket.connected) {
        return Promise.resolve()
      }

      // 等待连接完成（最多 10 秒）
      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('Connection timeout'))
        }, 10000)

        const checkInterval = setInterval(() => {
          if (this.socket?.connected) {
            clearTimeout(timeout)
            clearInterval(checkInterval)
            resolve()
          } else if (!globalSocket) {
            clearTimeout(timeout)
            clearInterval(checkInterval)
            reject(new Error('Socket was closed'))
          }
        }, 100)
      })
    }

    // 创建新 socket
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Connection timeout'))
      }, 10000)

      this.socket = io(this.url, {
        transports: ['websocket', 'polling'],
        reconnection: false,
        timeout: 10000,
        autoConnect: false,
      })

      // 保存到全局变量
      globalSocket = this.socket
      globalSocketUrl = this.url

      this.socket.on('connect', () => {
        clearTimeout(timeout)
        console.debug('[SocketClient] Connected:', this.socket?.id)
        resolve()
      })

      this.socket.on('connect_error', (error) => {
        clearTimeout(timeout)
        console.error('[SocketClient] Connection error:', error.message)
        reject(error)
      })

      this.socket.connect()
    })
  }

  /**
   * Disconnect from the server
   */
  disconnect(): void {
    if (this.socket) {
      this.socket.disconnect()
    }
  }

  /**
   * Register event listener
   */
  on<Event extends keyof SocketEvents>(
    event: Event,
    callback: SocketEvents[Event]
  ): void {
    if (!this.socket) {
      console.warn('[SocketClient] Cannot register event - socket not initialized')
      return
    }

    this.socket.on(event as any, callback as any)
  }

  /**
   * Unregister event listener
   */
  off<Event extends keyof SocketEvents>(
    event: Event,
    callback?: SocketEvents[Event]
  ): void {
    if (!this.socket) return

    if (callback) {
      this.socket.off(event as any, callback as any)
    } else {
      this.socket.off(event as any)
    }
  }

  /**
   * Emit event to server
   */
  emit<Event extends keyof SocketEmits>(
    event: Event,
    ...args: Parameters<SocketEmits[Event]>
  ): void {
    if (!this.socket) {
      console.warn('[SocketClient] Cannot emit - socket not initialized')
      return
    }

    if (!this.socket.connected) {
      console.warn('[SocketClient] Cannot emit - not connected')
      return
    }

    this.socket.emit(event as any, ...(args as any))
  }

  /** Get socket ID */
  get id(): string | undefined {
    return this.socket?.id
  }

  /** Check if connected */
  get connected(): boolean {
    return this.socket?.connected ?? false
  }

  /** Get raw socket instance */
  get raw(): Socket | null {
    return this.socket
  }
}
