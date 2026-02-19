/**
 * 对话 Hook
 * 管理对话状态、Socket.IO 事件监听、音频录制等
 */

import { useState, useEffect, useCallback, useRef } from "react"
import { io, Socket } from "socket.io-client"

// 服务器地址
const SERVER_URL = "http://localhost:12394"

// 消息类型
export interface Message {
  id: string
  sender: "user" | "ai"
  text: string
  time: string
  status?: "pending" | "sent" | "error"
}

// 对话状态
export type ConversationStatus = 
  | "idle"           // 空闲
  | "listening"      // 正在监听用户输入
  | "processing"     // 正在处理
  | "speaking"       // AI 正在说话
  | "interrupted"    // 被打断
  | "error"          // 错误

// Hook 配置
export interface UseConversationOptions {
  autoConnect?: boolean
  onStatusChange?: (status: ConversationStatus) => void
  onError?: (error: string) => void
}

// Hook 返回值
export interface UseConversationReturn {
  // 状态
  isConnected: boolean
  status: ConversationStatus
  messages: Message[]
  currentResponse: string
  isTyping: boolean
  error: string | null
  
  // 方法
  connect: () => void
  disconnect: () => void
  sendText: (text: string) => void
  startRecording: () => void
  stopRecording: () => void
  interrupt: () => void
  clearHistory: () => void
}

// 生成唯一 ID
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

// 获取当前时间
function getCurrentTime(): string {
  const now = new Date()
  return `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`
}

export function useConversation(options: UseConversationOptions = {}): UseConversationReturn {
  const { autoConnect = true, onStatusChange, onError } = options

  // 状态
  const [isConnected, setIsConnected] = useState(false)
  const [status, setStatus] = useState<ConversationStatus>("idle")
  const [messages, setMessages] = useState<Message[]>([])
  const [currentResponse, setCurrentResponse] = useState("")
  const [isTyping, setIsTyping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isRecording, setIsRecording] = useState(false)

  // Refs
  const socketRef = useRef<Socket | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const audioBufferRef = useRef<number[]>([])

  // 更新状态
  const updateStatus = useCallback((newStatus: ConversationStatus) => {
    setStatus(newStatus)
    onStatusChange?.(newStatus)
  }, [onStatusChange])

  // 添加消息
  const addMessage = useCallback((sender: "user" | "ai", text: string) => {
    const message: Message = {
      id: generateId(),
      sender,
      text,
      time: getCurrentTime(),
    }
    setMessages((prev) => [...prev, message])
    return message.id
  }, [])

  // 更新消息
  const updateMessage = useCallback((id: string, updates: Partial<Message>) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === id ? { ...msg, ...updates } : msg))
    )
  }, [])

  // 初始化 Socket.IO
  useEffect(() => {
    const socket = io(SERVER_URL, {
      transports: ["websocket", "polling"],
      autoConnect: false,
    })

    socketRef.current = socket

    // 连接成功
    socket.on("connect", () => {
      console.log("[Conversation] 已连接到服务器:", socket.id)
      setIsConnected(true)
      setError(null)
    })

    // 断开连接
    socket.on("disconnect", (reason) => {
      console.log("[Conversation] 已断开连接:", reason)
      setIsConnected(false)
      updateStatus("idle")
    })

    // 连接错误
    socket.on("connect_error", (err) => {
      console.error("[Conversation] 连接错误:", err.message)
      setError(`连接失败: ${err.message}`)
      onError?.(`连接失败: ${err.message}`)
    })

    // 连接确认
    socket.on("connection-established", (data) => {
      console.log("[Conversation] 服务器确认连接:", data)
    })

    // ========== 新事件格式 ==========

    // 接收文本消息
    socket.on("text", (data: { text: string; from_name?: string }) => {
      console.log("[Conversation] 收到文本:", data.text)
      
      // 追加到当前响应
      setCurrentResponse((prev) => prev + data.text)
      
      // 如果是完整消息，添加到消息列表
      if (data.from_name === "AI") {
        setIsTyping(false)
        addMessage("ai", data.text)
        setCurrentResponse("")
        updateStatus("idle")
      }
    })

    // 接收音频
    socket.on("audio", (data: { audio_url?: string; audio_data?: string; seq?: number }) => {
      console.log("[Conversation] 收到音频:", data.audio_url || `数据长度: ${data.audio_data?.length || 0}`)
      updateStatus("speaking")
      
      // 如果有音频数据，播放
      if (data.audio_data) {
        playAudioFromHex(data.audio_data)
      }
    })

    // 接收控制信号
    socket.on("control", (data: { text: string }) => {
      console.log("[Conversation] 控制信号:", data.text)
      
      switch (data.text) {
        case "start-mic":
          updateStatus("listening")
          break
        case "interrupt":
        case "interrupted":
          updateStatus("interrupted")
          setIsTyping(false)
          setCurrentResponse("")
          break
        case "mic-audio-end":
          updateStatus("processing")
          break
        case "no-audio-data":
          updateStatus("idle")
          break
        case "conversation-start":
          updateStatus("processing")
          break
        case "conversation-end":
          updateStatus("idle")
          break
      }
    })

    // 接收工具调用
    socket.on("tool_call", (data: { name: string; args: Record<string, unknown> }) => {
      console.log("[Conversation] 工具调用:", data.name, data.args)
    })

    // 错误
    socket.on("error", (data: { message: string }) => {
      console.error("[Conversation] 服务器错误:", data.message)
      setError(data.message)
      onError?.(data.message)
      updateStatus("error")
    })

    // ========== 兼容旧事件格式 ==========

    // 完整文本（旧格式）
    socket.on("full-text", (data: { type: string; text: string }) => {
      console.log("[Conversation] 收到完整文本:", data.text)
      setIsTyping(false)
      addMessage("ai", data.text)
      setCurrentResponse("")
      updateStatus("idle")
    })

    // ASR 结果
    socket.on("transcript", (data: { text: string; is_final: boolean }) => {
      console.log("[Conversation] ASR 结果:", data.text, "is_final:", data.is_final)
      if (data.is_final && data.text) {
        addMessage("user", data.text)
      }
    })

    // 历史记录
    socket.on("history-list", (data: { histories: Array<{ uid: string; preview: string }> }) => {
      console.log("[Conversation] 历史列表:", data.histories.length)
    })

    socket.on("history-data", (data: { messages: Array<{ role: string; content: string }> }) => {
      console.log("[Conversation] 历史数据:", data.messages.length)
      // 将历史消息转换为消息列表
      const historyMessages = data.messages.map((msg, index) => ({
        id: `history-${index}`,
        sender: msg.role === "user" ? "user" as const : "ai" as const,
        text: msg.content,
        time: "",
      }))
      setMessages(historyMessages)
    })

    // 自动连接
    if (autoConnect) {
      socket.connect()
    }

    return () => {
      socket.disconnect()
      socketRef.current = null
    }
  }, [autoConnect, addMessage, updateStatus, onError])

  // 播放音频（从 hex 字符串）
  const playAudioFromHex = useCallback((hexData: string) => {
    try {
      // 将 hex 转换为 ArrayBuffer
      const binaryString = atob(hexData)
      const bytes = new Uint8Array(binaryString.length)
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i)
      }

      // 创建音频上下文
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext()
      }

      // 解码并播放
      audioContextRef.current.decodeAudioData(bytes.buffer, (audioBuffer) => {
        const source = audioContextRef.current!.createBufferSource()
        source.buffer = audioBuffer
        source.connect(audioContextRef.current!.destination)
        source.start(0)
        
        source.onended = () => {
          updateStatus("idle")
        }
      })
    } catch (err) {
      console.error("[Conversation] 播放音频出错:", err)
    }
  }, [updateStatus])

  // 连接
  const connect = useCallback(() => {
    if (socketRef.current && !socketRef.current.connected) {
      socketRef.current.connect()
    }
  }, [])

  // 断开连接
  const disconnect = useCallback(() => {
    if (socketRef.current?.connected) {
      socketRef.current.disconnect()
    }
  }, [])

  // 发送文本
  const sendText = useCallback((text: string) => {
    if (!text.trim()) return

    // 添加用户消息
    addMessage("user", text)
    
    // 发送到服务器
    if (socketRef.current?.connected) {
      setIsTyping(true)
      updateStatus("processing")
      socketRef.current.emit("text_input", { text })
    } else {
      setError("未连接到服务器")
      onError?.("未连接到服务器")
    }
  }, [addMessage, updateStatus, onError])

  // 开始录制音频
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          sampleRate: 16000,
          channelCount: 1,
        } 
      })
      
      mediaStreamRef.current = stream
      
      const audioContext = new AudioContext({ sampleRate: 16000 })
      audioContextRef.current = audioContext
      
      const source = audioContext.createMediaStreamSource(stream)
      const processor = audioContext.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor
      
      source.connect(processor)
      processor.connect(audioContext.destination)
      
      audioBufferRef.current = []
      
      processor.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0)
        
        // 转换为 16-bit PCM
        const pcmData = new Int16Array(inputData.length)
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]))
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
        }
        
        // 发送音频数据到服务器
        if (socketRef.current?.connected) {
          socketRef.current.emit("raw_audio_data", {
            audio: Array.from(pcmData)
          })
        }
        
        audioBufferRef.current.push(...Array.from(inputData))
      }
      
      setIsRecording(true)
      updateStatus("listening")
      
    } catch (err) {
      console.error("[Conversation] 录音启动失败:", err)
      setError("无法访问麦克风")
      onError?.("无法访问麦克风")
    }
  }, [updateStatus, onError])

  // 停止录制
  const stopRecording = useCallback(() => {
    // 停止媒体流
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop())
      mediaStreamRef.current = null
    }
    
    // 断开音频处理节点
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
    
    // 关闭音频上下文
    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }
    
    setIsRecording(false)
    
    // 通知服务器音频结束
    if (socketRef.current?.connected && audioBufferRef.current.length > 0) {
      socketRef.current.emit("mic_audio_end", {})
      updateStatus("processing")
    } else {
      updateStatus("idle")
    }
    
    audioBufferRef.current = []
  }, [updateStatus])

  // 打断
  const interrupt = useCallback(() => {
    if (socketRef.current?.connected) {
      socketRef.current.emit("interrupt_signal", { 
        text: currentResponse 
      })
    }
    setCurrentResponse("")
    setIsTyping(false)
    updateStatus("interrupted")
  }, [currentResponse, updateStatus])

  // 清空历史
  const clearHistory = useCallback(() => {
    setMessages([])
    if (socketRef.current?.connected) {
      socketRef.current.emit("clear_history", {})
    }
  }, [])

  return {
    // 状态
    isConnected,
    status,
    messages,
    currentResponse,
    isTyping,
    error,
    
    // 方法
    connect,
    disconnect,
    sendText,
    startRecording,
    stopRecording,
    interrupt,
    clearHistory,
  }
}