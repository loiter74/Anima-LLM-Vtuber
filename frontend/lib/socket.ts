/**
 * Socket.IO 客户端服务
 * 连接到后端 Socket.IO 服务器
 */

import { io, Socket } from "socket.io-client"

// 服务器地址
const SERVER_URL = "http://localhost:12394"

// Socket 实例（单例模式）
let socket: Socket | null = null

/**
 * 获取 Socket 实例
 * 如果尚未连接，则创建新连接
 */
export function getSocket(): Socket {
  if (!socket) {
    socket = io(SERVER_URL, {
      transports: ["websocket", "polling"],
      autoConnect: false, // 手动连接
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
export function sendTextMessage(text: string): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("text_input", { text })
  } else {
    console.warn("[Socket] 未连接，无法发送消息")
  }
}

/**
 * 发送打断信号
 */
export function sendInterrupt(): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("interrupt_signal", { text: "用户打断" })
  }
}

/**
 * 请求历史记录
 */
export function fetchHistory(): void {
  const socket = getSocket()
  if (socket.connected) {
    socket.emit("fetch_history_list", {})
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

// 导出类型
export type { Socket }