/**
 * Socket.IO 客户端服务
 * 连接到后端 Socket.IO 服务器
 * 
 * 注意：推荐使用 useConversation hook 进行对话操作
 * 此文件提供底层 Socket.IO 连接管理
 */

import { io, Socket } from "socket.io-client"

// 服务器地址
const SERVER_URL = "http://localhost:12394"

// Socket 实例（单例模式）
let socket: Socket | null = null

// 事件类型定义
export interface SocketEvents {
  // 连接事件
  "connection-established": { message: string; sid: string }
  
  // 对话事件
  "text": { text: string; from_name?: string }
  "audio": { audio_url?: string; audio_data?: string; seq?: number }
  "control": { text: string }
  "tool_call": { name: string; args: Record<string, unknown> }
  "error": { message: string }
  
  // 兼容旧事件
  "full-text": { type: string; text: string }
  "transcript": { text: string; is_final: boolean }
  
  // 历史记录
  "history-list": { histories: Array<{ uid: string; preview: string }> }
  "history-data": { messages: Array<{ role: string; content: string }> }
  "history-cleared": { type: string }
  "new-history-created": { type: string; history_uid: string }
  
  // 配置
  "config-switched": { type: string; message: string }
}

/**
 * 获取 Socket 实例
 * 如果尚未连接，则创建新连接
 */
export function getSocket(): Socket {
  if (!socket) {
    socket = io(SERVER_URL, {
      transports: ["websocket", "polling"],
      autoConnect: false, // 手动连接
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 20000,
    })

    // 连接事件
    socket.on("connect", () => {
      console.log("[Socket] 已连接到服务器:", socket?.id)
    })

    socket.on("disconnect", (reason) => {
      console.log("[Socket] 已断开连接:", reason)
    })

    socket.on("connect_error", (error) => {
      console.error("[Socket] 连接错误:", error.message)
    })
  }

  return socket
}

/**
 * 连接到服务器
 */
export function connectSocket(): void {
  const socket = getSocket()
  if (!socket.connected) {
    socket.connect()
  }
}

/**
 * 断开连接
 */
export function disconnectSocket(): void {
  if (socket?.connected) {
    socket.disconnect()
  }
}

/**
 * 发送文本消息
 */
export function sendTextMessage(text: string, metadata?: Record<string, unknown>): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("text_input", { text, metadata })
  } else {
    console.warn("[Socket] 未连接，无法发送消息")
  }
}

/**
 * 发送打断信号
 */
export function sendInterrupt(heardText?: string): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("interrupt_signal", { text: heardText || "" })
  }
}

/**
 * 发送音频数据
 */
export function sendAudioData(audio: number[]): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("raw_audio_data", { audio })
  }
}

/**
 * 通知音频结束
 */
export function sendAudioEnd(): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("mic_audio_end", {})
  }
}

/**
 * 请求历史记录列表
 */
export function fetchHistoryList(): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("fetch_history_list", {})
  }
}

/**
 * 请求特定历史记录
 */
export function fetchHistory(historyUid: string): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("fetch_history", { history_uid: historyUid })
  }
}

/**
 * 清空对话历史
 */
export function clearHistory(): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("clear_history", {})
  }
}

/**
 * 切换配置
 */
export function switchConfig(file: string): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("switch_config", { file })
  }
}

/**
 * 创建新对话历史
 */
export function createNewHistory(): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("create_new_history", {})
  }
}

// 导出类型
export type { Socket }