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
  sendTestAudio: () => void  // 发送模拟测试音频
  sendRealTestAudio: (filename?: string) => Promise<void>  // 发送真实测试音频
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
  const handlerIdRef = useRef<string>(`handler-${Math.random().toString(36).substr(2, 9)}`)  // 唯一标识符
  const registrationCountRef = useRef<number>(0)  // 追踪注册次数
  const handleSentenceCallCountRef = useRef<number>(0)  // 追踪 handleSentence 调用次数
  const lastProcessedCompleteSeqRef = useRef<number>(-1)  // 追踪上一次处理的完成标记 seq，防止重复
  const shouldSendAudioRef = useRef<boolean>(true)  // 控制是否发送音频数据（VAD 暂停标志）
  const startRecordingRef = useRef<(() => void) | null>(null)  // 保存 startRecording 函数引用
  const isRecordingRef = useRef<boolean>(false)  // 跟踪录音状态

  // 使用 ref 存储外部回调函数
  const onStatusChangeRef = useRef(onStatusChange)
  const onErrorRef = useRef(onError)

  // 更新状态
  const updateStatus = useCallback((newStatus: ConversationStatus) => {
    setStatus(newStatus)
    onStatusChangeRef.current?.(newStatus)
  }, [])

  // 添加消息
  const addMessage = useCallback((sender: "user" | "ai", text: string) => {
    const currentTime = getCurrentTime()

    setMessages((prev) => {
      // 检查最后一条消息是否完全相同（React 双重调用会产生连续的相同消息）
      if (prev.length > 0) {
        const lastMsg = prev[prev.length - 1]
        if (lastMsg.sender === sender && lastMsg.text === text && lastMsg.time === currentTime) {
          console.log(`[addMessage-${handlerIdRef.current}] 检测到重复消息，跳过 - 发送者: ${sender}, 文本: ${text.substring(0, 30)}`)
          return prev
        }
      }

      const messageId = generateId()
      const message: Message = {
        id: messageId,
        sender,
        text,
        time: currentTime,
      }

      console.log(`[addMessage-${handlerIdRef.current}] 添加消息 - ID: ${messageId}, 发送者: ${sender}, 文本: ${text.substring(0, 50)}`)
      return [...prev, message]
    })
  }, [])

  // 更新消息
  const updateMessage = useCallback((id: string, updates: Partial<Message>) => {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === id ? { ...msg, ...updates } : msg))
    )
  }, [])

  // 播放音频（从 base64 字符串）
  const playAudioFromHex = useCallback((base64Data: string) => {
    try {
      console.log("[Conversation] 开始播放音频，数据长度:", base64Data.length)

      // 将 base64 转换为 Blob URL
      const binaryString = atob(base64Data)
      const bytes = new Uint8Array(binaryString.length)
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i)
      }

      // 创建 Blob 和 URL
      const blob = new Blob([bytes], { type: 'audio/mpeg' })
      const audioUrl = URL.createObjectURL(blob)

      console.log("[Conversation] 创建音频 Blob URL:", audioUrl)

      // 使用 HTML5 Audio 元素播放 MP3
      const audio = new Audio(audioUrl)

      audio.oncanplaythrough = () => {
        console.log("[Conversation] 音频可以播放")
        audio.play().catch(err => {
          console.error("[Conversation] 音频播放失败:", err)
          updateStatus("idle")
        })
      }

      audio.onended = () => {
        console.log("[Conversation] 音频播放完成")
        updateStatus("idle")
        URL.revokeObjectURL(audioUrl) // 释放内存
      }

      audio.onerror = (e) => {
        console.error("[Conversation] 音频加载错误:", e)
        updateStatus("idle")
        URL.revokeObjectURL(audioUrl)
      }

    } catch (err) {
      console.error("[Conversation] 播放音频出错:", err)
      updateStatus("idle")
    }
  }, [updateStatus])

  // 使用 ref 存储内部回调函数，避免 useEffect 重复执行
  const addMessageRef = useRef(addMessage)
  const updateStatusRef = useRef(updateStatus)
  const setIsTypingRef = useRef(setIsTyping)
  const setCurrentResponseRef = useRef(setCurrentResponse)
  const playAudioRef = useRef(playAudioFromHex)

  // 更新 ref
  useEffect(() => {
    onStatusChangeRef.current = onStatusChange
    onErrorRef.current = onError
    addMessageRef.current = addMessage
    updateStatusRef.current = updateStatus
    setIsTypingRef.current = setIsTyping
    setCurrentResponseRef.current = setCurrentResponse
    playAudioRef.current = playAudioFromHex
  })

  // 句子事件处理函数（稳定引用）
  const handleSentence = useCallback((data: { text: string; type: string; seq: number }) => {
    handleSentenceCallCountRef.current += 1
    console.log(`[handleSentence-${handlerIdRef.current}] 收到事件 (第${handleSentenceCallCountRef.current}次调用) - seq: ${data.seq}, 文本: "${data.text}", 类型: ${data.type}`)

    // 空文本表示完成标记
    if (data.text === "") {
      // 防止重复处理同一个完成标记（React 双渲染问题）
      if (data.seq === lastProcessedCompleteSeqRef.current) {
        console.log(`[handleSentence-${handlerIdRef.current}] 跳过重复的完成标记 seq=${data.seq}`)
        return
      }

      console.log(`[handleSentence-${handlerIdRef.current}] 检测到完成标记 seq=${data.seq}，准备添加消息`)
      lastProcessedCompleteSeqRef.current = data.seq

      // 将完整的响应添加到消息列表
      setCurrentResponseRef.current?.((prevResponse: string) => {
        console.log(`[handleSentence-${handlerIdRef.current}] 当前完整响应: "${prevResponse}"`)
        if (prevResponse) {
          console.log(`[handleSentence-${handlerIdRef.current}] 调用 addMessage("ai", "${prevResponse}")`)
          addMessageRef.current?.("ai", prevResponse)
        } else {
          console.log(`[handleSentence-${handlerIdRef.current}] 警告：prevResponse 为空，跳过添加`)
        }
        return ""
      })
      setIsTypingRef.current?.(false)
      updateStatusRef.current?.("idle")
      console.log(`[handleSentence-${handlerIdRef.current}] 完成标记处理完毕`)
    } else {
      // 追加到当前响应
      console.log(`[handleSentence-${handlerIdRef.current}] 追加文本: "${data.text}"`)
      setCurrentResponseRef.current?.((prev: string) => {
        const newText = prev + data.text
        console.log(`[handleSentence-${handlerIdRef.current}] 响应更新: "${prev}" + "${data.text}" = "${newText}"`)
        return newText
      })
    }
  }, [])  // 空依赖数组，函数引用稳定

  // 初始化 Socket.IO
  useEffect(() => {
    console.log("[useEffect] Socket.IO 初始化开始")
    const socket = io(SERVER_URL, {
      transports: ["websocket", "polling"],
      autoConnect: false,
    })

    socketRef.current = socket
    console.log("[useEffect] Socket 实例已创建")

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
      updateStatusRef.current?.("idle")
    })

    // 连接错误
    socket.on("connect_error", (err) => {
      console.error("[Conversation] 连接错误:", err.message)
      setError(`连接失败: ${err.message}`)
      onErrorRef.current?.(`连接失败: ${err.message}`)
    })

    // 连接确认
    socket.on("connection-established", (data) => {
      console.log("[Conversation] 服务器确认连接:", data)
    })

    // ========== 新事件格式 ==========

    // 接收流式文本片段（sentence事件）- 这是唯一的消息接收方式
    registrationCountRef.current += 1
    console.log(`[useEffect-${handlerIdRef.current}] 注册 sentence 事件监听器 (第${registrationCountRef.current}次注册), handleSentence 引用:`, handleSentence.name || 'anonymous')
    socket.on("sentence", handleSentence)

    // 检查 Socket.IO 内部监听器数量（调试用）
    try {
      const ioListeners = (socket as any).io?.opts?.transforms || []
      const eventListeners = (socket as any)._callbacks || {}
      const sentenceListeners = Object.keys(eventListeners).filter((k) => k.includes("sentence")).length
      console.log(`[useEffect-${handlerIdRef.current}] sentence 事件监听器已注册, 检测到的监听器数量: ${sentenceListeners}`)

      if (sentenceListeners > 1) {
        console.error(`[useEffect-${handlerIdRef.current}] ⚠️ 警告：检测到 ${sentenceListeners} 个 sentence 事件监听器！这可能导致重复消息！`)
      }
    } catch (err) {
      console.log(`[useEffect-${handlerIdRef.current}] sentence 事件监听器已注册`)
    }

    // 接收音频
    socket.on("audio", (data: { audio_url?: string; audio_data?: string; seq?: number }) => {
      console.log("[Conversation] 收到音频:", data.audio_url || `数据长度: ${data.audio_data?.length || 0}`)

      // 只有在有音频数据时才更新状态并播放
      if (data.audio_data) {
        updateStatusRef.current?.("speaking")
        playAudioRef.current?.(data.audio_data)
      } else {
        console.log("[Conversation] ⚠️ 收到空音频事件，忽略")
      }
    })

    // 接收控制信号
    socket.on("control", (data: { text: string }) => {
      console.log("[Conversation] 控制信号:", data.text)

      const updateStatus = updateStatusRef.current
      const setIsTyping = setIsTypingRef.current
      const setCurrentResponse = setCurrentResponseRef.current

      switch (data.text) {
        case "start-mic":
          // 如果还没开始录音，自动启动录音
          if (!isRecordingRef.current) {
            console.log("[Conversation] 🎙️ 收到 start-mic 信号，自动启动录音")
            startRecordingRef.current?.()
          } else {
            console.log("[Conversation] ♻️ 收到 start-mic 信号，录音已在运行，恢复发送音频数据")
            shouldSendAudioRef.current = true  // 恢复发送音频
            updateStatus?.("listening")
          }
          break
        case "interrupt":
        case "interrupted":
          updateStatus?.("interrupted")
          setIsTyping?.(false)
          setCurrentResponse?.("")
          shouldSendAudioRef.current = true  // 打断后恢复发送
          console.log("[Conversation] ✅ 打断，恢复发送音频数据")
          break
        case "mic-audio-end":
          updateStatus?.("processing")
          shouldSendAudioRef.current = false  // 暂停发送音频
          console.log("[Conversation] ⏸️ VAD 检测到语音结束，暂停发送音频数据")
          break
        case "no-audio-data":
          updateStatus?.("idle")
          shouldSendAudioRef.current = true  // 无数据时恢复发送
          console.log("[Conversation] ⚠️ 无音频数据，恢复发送")
          break
        case "conversation-start":
          updateStatus?.("processing")
          shouldSendAudioRef.current = false  // 开始处理时暂停
          break
        case "conversation-end":
          updateStatus?.("idle")
          shouldSendAudioRef.current = true  // 处理结束，恢复发送
          console.log("[Conversation] ✅ 对话结束，恢复发送音频数据")
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
      onErrorRef.current?.(data.message)
      updateStatusRef.current?.("error")
    })

    // ========== 兼容旧事件格式 ==========

    // ASR 结果
    socket.on("transcript", (data: { text: string; is_final: boolean }) => {
      console.log("[Conversation] ASR 结果:", data.text, "is_final:", data.is_final)
      if (data.is_final && data.text) {
        addMessageRef.current?.("user", data.text)
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
      console.log(`[useEffect cleanup-${handlerIdRef.current}] 清理函数执行 (第${registrationCountRef.current}次注册后)`)
      console.log(`[useEffect cleanup-${handlerIdRef.current}] 移除 sentence 事件监听器, handleSentence 引用:`, handleSentence.name || 'anonymous')
      // 移除所有事件监听器，防止重复注册
      socket.off("sentence", handleSentence)
      console.log(`[useEffect cleanup-${handlerIdRef.current}] sentence 事件监听器已移除`)
      socket.disconnect()
      socketRef.current = null
      console.log(`[useEffect cleanup-${handlerIdRef.current}] Socket 已断开并清理`)
    }
  }, [autoConnect, handleSentence])  // 依赖 handleSentence

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
      // 清空之前的响应（修复消息合并问题）
      setCurrentResponse("")
      setIsTyping(true)
      updateStatus("processing")
      socketRef.current.emit("text_input", { text })

      // 设置超时，如果30秒内没有响应则重置状态
      const timeout = setTimeout(() => {
        setIsTyping((prevIsTyping) => {
          if (prevIsTyping) {
            console.warn("[Conversation] 响应超时，重置状态")
            updateStatus("idle")
            setError("响应超时，请重试")
            onErrorRef.current?.("响应超时，请重试")
            return false
          }
          return prevIsTyping
        })
      }, 30000)

      // 保存 timeout ID 以便清理（可选）
      ;(sendText as any)._timeout = timeout
    } else {
      setError("未连接到服务器")
      onErrorRef.current?.("未连接到服务器")
      // 连接失败时重置状态，避免输入框被禁用
      setIsTyping(false)
      updateStatus("idle")
    }
  }, [addMessage, updateStatus])

  // 开始录制音频
  // TODO: 考虑迁移到 AudioWorklet API（createScriptProcessor 已被废弃）
  const startRecording = useCallback(async () => {
    try {
      // 先检查权限状态（如果浏览器支持）
      if (navigator.permissions) {
        try {
          const permissionStatus = await navigator.permissions.query({ name: 'microphone' as PermissionName })
          if (permissionStatus.state === 'denied') {
            const errorMsg = "麦克风权限被拒绝。请在浏览器地址栏点击锁图标，允许麦克风访问后刷新页面。"
            setError(errorMsg)
            onErrorRef.current?.(errorMsg)
            onError?.(errorMsg)
            return
          }
        } catch (err) {
          // 某些浏览器不支持查询麦克风权限状态，忽略错误
          console.log("[Conversation] 无法查询麦克风权限状态:", err)
        }
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        }
      })
      
      mediaStreamRef.current = stream
      
      const audioContext = new AudioContext({ sampleRate: 16000 })
      audioContextRef.current = audioContext
      
      const source = audioContext.createMediaStreamSource(stream)
      const processor = audioContext.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      // 连接音频处理节点
      source.connect(processor)
      // 注意：不连接到 audioContext.destination，避免麦克风回声

      audioBufferRef.current = []

      // 音频块计数器
      let audioChunkCount = 0
      let lastLogTime = Date.now()

      processor.onaudioprocess = (event) => {
        audioChunkCount++

        // 每 5 秒打印一次心跳日志
        const now = Date.now()
        if (now - lastLogTime > 5000) {
          console.log(`[Conversation] 💓 onaudioprocess 心跳: 已处理 ${audioChunkCount} 个块`)
          console.log(`[Conversation]    - socket connected: ${socketRef.current?.connected}`)
          console.log(`[Conversation]    - shouldSendAudio: ${shouldSendAudioRef.current}`)
          lastLogTime = now
        }

        const inputData = event.inputBuffer.getChannelData(0)

        // 每 10 个块打印一次音频统计
        if (audioChunkCount % 10 === 1) {
          const min = Math.min(...inputData)
          const max = Math.max(...inputData)
          const mean = inputData.reduce((sum, v) => sum + Math.abs(v), 0) / inputData.length
          console.log(`[Conversation] 🎙️ 录音块 #${audioChunkCount}: ${inputData.length} samples`)
          console.log(`  Range: [${min.toFixed(4)}, ${max.toFixed(4)}], Mean: ${mean.toFixed(4)}`)
        }

        // 转换为 16-bit PCM（节省带宽）
        const pcmData = new Int16Array(inputData.length)
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]))
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
        }

        // 只有在 shouldSendAudio 为 true 时才发送音频数据
        // 这样可以在 AI 回复时暂停发送音频，避免数据混杂
        if (socketRef.current?.connected && shouldSendAudioRef.current) {
          socketRef.current.emit("raw_audio_data", {
            audio: Array.from(pcmData)
          })

          // 通知音频块已发送（供 VolumeMonitor 使用）
          window.dispatchEvent(new CustomEvent('audio-chunk-sent'))

          // 每 100 个块打印一次日志
          if (audioChunkCount % 100 === 1) {
            console.log(`[Conversation] 🎙️ 发送音频块 #${audioChunkCount}, 长度: ${pcmData.length} 采样点`)
          }
        } else {
          // 每 100 个块打印一次未发送的原因
          if (audioChunkCount % 100 === 1) {
            if (!socketRef.current?.connected) {
              console.warn(`[Conversation] ⚠️ 未连接到服务器，跳过发送块 #${audioChunkCount}`)
            } else if (!shouldSendAudioRef.current) {
              console.log(`[Conversation] ⏸️ 音频暂停发送 (shouldSendAudio=false), 块 #${audioChunkCount}`)
            }
          }
        }

        // 保存原始音频数据用于fallback（如果VAD未检测到语音结束）
        audioBufferRef.current.push(...Array.from(inputData))
      }

      console.log("[Conversation] ✅ 录音已启动，开始发送音频数据")

      console.log("[Conversation] ✅ 录音已启动，开始发送音频数据")

      setIsRecording(true)
      isRecordingRef.current = true

      // 通知录音状态变化（供 VolumeMonitor 使用）
      ;(window as any).__isRecording = true
      window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: true }))

      updateStatus("listening")
      
    } catch (err) {
      console.error("[Conversation] 录音启动失败:", err)

      // 提供更友好的错误信息
      let errorMessage = "无法访问麦克风"

      if (err instanceof DOMException) {
        if (err.name === 'NotAllowedError') {
          errorMessage = "麦克风权限被拒绝。请点击浏览器地址栏的锁图标，允许" +
            (window.location.protocol === 'https:' ? '' : '在 https 或 localhost 环境下') +
            "麦克风访问权限。"
        } else if (err.name === 'NotFoundError') {
          errorMessage = "未检测到麦克风设备。请连接麦克风后重试。"
        } else if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost') {
          errorMessage = "浏览器安全限制：麦克风权限需要 HTTPS 或 localhost 环境。"
        }
      }

      setError(errorMessage)
      onErrorRef.current?.(errorMessage)
      onError?.(errorMessage)
    }
  }, [updateStatus, onError, onErrorRef])

  // 更新 startRecording ref
  useEffect(() => {
    startRecordingRef.current = startRecording
  }, [startRecording])

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
    isRecordingRef.current = false

    // 通知录音状态变化（供 VolumeMonitor 使用）
    ;(window as any).__isRecording = false
    window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: false }))

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
  }, [currentResponse])

  // 清空历史
  const clearHistory = useCallback(() => {
    setMessages([])
    if (socketRef.current?.connected) {
      socketRef.current.emit("clear_history", {})
    }
  }, [])

  // 发送测试音频（模拟真实语音数据）
  const sendTestAudio = useCallback(() => {
    console.log("[Conversation] 🧪 开始发送测试音频数据")

    if (!socketRef.current?.connected) {
      console.error("[Conversation] ❌ 未连接到服务器")
      setError("未连接到服务器")
      return
    }

    // 生成模拟的音频数据（16-bit PCM，模拟语音）
    const sampleRate = 16000
    const duration = 3  // 3秒
    const totalSamples = sampleRate * duration

    console.log(`[Conversation] 🧪 生成 ${duration} 秒测试音频（${totalSamples} 个采样点）`)

    // 分块发送（每块 4096 个采样点，与真实的 audio processor 相同）
    const chunkSize = 4096
    let sentChunks = 0

    const sendInterval = setInterval(() => {
      if (sentChunks >= totalSamples / chunkSize) {
        clearInterval(sendInterval)
        console.log(`[Conversation] ✅ 测试音频发送完成，共发送 ${sentChunks} 个块`)

        // 🔥 关键修复：发送静音块来触发VAD的语音结束检测
        console.log("[Conversation] 🎯 发送静音块，触发VAD语音结束")

        // 发送至少30个静音块（30 * 4096 / 16000 ≈ 7.7秒，超过VAD的24个块阈值）
        const silenceChunks = 30
        let sentSilenceChunks = 0

        const silenceInterval = setInterval(() => {
          if (sentSilenceChunks >= silenceChunks) {
            clearInterval(silenceInterval)
            console.log(`[Conversation] ✅ 静音块发送完成`)
            return
          }

          // 生成全零的静音数据
          const silenceData = new Int16Array(chunkSize).fill(0)

          socketRef.current.emit("raw_audio_data", {
            audio: Array.from(silenceData)
          })

          sentSilenceChunks++

          if (sentSilenceChunks % 10 === 1) {
            console.log(`[Conversation] 🤫 发送静音块 #${sentSilenceChunks}/${silenceChunks}`)
          }
        }, 10)  // 每 10ms 发送一块

        return
      }

      // 生成模拟的音频数据（模拟语音波形）
      const pcmData = new Int16Array(chunkSize)
      for (let i = 0; i < chunkSize; i++) {
        const t = (sentChunks * chunkSize + i) / sampleRate

        // 🔥 改进的语音模拟：更丰富的频率 + 振幅调制
        // 基础频率（类似人声基频 150-300Hz）
        const baseFreq = 200 + Math.sin(t * 0.5) * 50  // 150-250Hz 波动
        // 振幅调制（模拟说话的强弱变化）
        const amplitude = 0.6 + Math.sin(t * 3) * 0.2 + Math.sin(t * 7) * 0.1  // 0.3-0.9

        // 多频率合成（模拟共振峰）
        const signal = (
          // 基频
          Math.sin(2 * Math.PI * baseFreq * t) * amplitude +
          // 泛音 1 (2x)
          Math.sin(2 * Math.PI * baseFreq * 2 * t) * amplitude * 0.5 +
          // 泛音 2 (3x)
          Math.sin(2 * Math.PI * baseFreq * 3 * t) * amplitude * 0.3 +
          // 泛音 3 (4x)
          Math.sin(2 * Math.PI * baseFreq * 4 * t) * amplitude * 0.15 +
          // 高频成分（模拟摩擦音）
          Math.sin(2 * Math.PI * 3000 * t) * amplitude * 0.08 +
          Math.sin(2 * Math.PI * 4500 * t) * amplitude * 0.05 +
          // 噪声（模拟气流声）
          (Math.random() - 0.5) * 0.15
        ) * 0.7  // 总体增益

        pcmData[i] = Math.max(-32768, Math.min(32767, signal * 32767))
      }

      // 发送音频数据
      socketRef.current.emit("raw_audio_data", {
        audio: Array.from(pcmData)
      })

      sentChunks++

      // 每 10 个块打印一次日志和音频统计
      if (sentChunks % 10 === 1) {
        // 计算音频统计
        const min = Math.min(...Array.from(pcmData))
        const max = Math.max(...Array.from(pcmData))
        const mean = pcmData.reduce((sum, v) => sum + Math.abs(v), 0) / pcmData.length

        console.log(`[Conversation] 🧪 发送测试音频块 #${sentChunks}/${totalSamples / chunkSize}`)
        console.log(`  Audio: ${pcmData.length} samples, range=[${min}, ${max}], mean=${mean.toFixed(2)}`)
      }
    }, 10)  // 每 10ms 发送一块

    updateStatus("listening")
  }, [updateStatus])

  // 发送真实的测试音频（从文件加载）
  const sendRealTestAudio = useCallback(async (filename: string = "test_chinese_female.mp3") => {
    console.log(`[Conversation] 🎵 开始发送真实测试音频: ${filename}`)

    if (!socketRef.current?.connected) {
      console.error("[Conversation] ❌ 未连接到服务器")
      setError("未连接到服务器")
      return
    }

    try {
      // 加载音频文件
      const audioUrl = `/test_audio/${filename}`
      console.log(`[Conversation] 📂 加载音频: ${audioUrl}`)

      const response = await fetch(audioUrl)
      if (!response.ok) {
        throw new Error(`Failed to load audio: ${response.status}`)
      }

      const arrayBuffer = await response.arrayBuffer()
      console.log(`[Conversation] ✅ 音频加载成功: ${arrayBuffer.byteLength} 字节`)

      // 解码音频数据
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: 16000  // 确保使用 16kHz 采样率
      })

      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer)
      console.log(`[Conversation] ✅ 音频解码成功:`)
      console.log(`   - 时长: ${audioBuffer.duration.toFixed(2)} 秒`)
      console.log(`   - 采样率: ${audioBuffer.sampleRate} Hz`)
      console.log(`   - 声道数: ${audioBuffer.numberOfChannels}`)

      // 获取 PCM 数据（单声道）
      const pcmData = audioBuffer.getChannelData(0)  // Float32Array

      // 转换为 Int16 PCM
      const int16Data = new Int16Array(pcmData.length)
      for (let i = 0; i < pcmData.length; i++) {
        const s = Math.max(-1, Math.min(1, pcmData[i]))
        int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
      }

      console.log(`[Conversation] ✅ 转换为 Int16 PCM: ${int16Data.length} 采样点`)

      // 分块发送
      const chunkSize = 4096
      const totalChunks = Math.ceil(int16Data.length / chunkSize)
      let sentChunks = 0

      const sendInterval = setInterval(() => {
        if (sentChunks >= totalChunks) {
          clearInterval(sendInterval)
          console.log(`[Conversation] ✅ 真实音频发送完成，共发送 ${sentChunks} 个块`)

          // 发送静音块触发 VAD 语音结束检测
          console.log("[Conversation] 🎯 发送静音块，触发VAD语音结束")
          const silenceChunks = 30
          let sentSilenceChunks = 0

          const silenceInterval = setInterval(() => {
            if (sentSilenceChunks >= silenceChunks) {
              clearInterval(silenceInterval)
              console.log(`[Conversation] ✅ 静音块发送完成`)
              return
            }

            const silenceData = new Int16Array(chunkSize).fill(0)
            socketRef.current!.emit("raw_audio_data", {
              audio: Array.from(silenceData)
            })

            sentSilenceChunks++
            if (sentSilenceChunks % 10 === 1) {
              console.log(`[Conversation] 🤫 发送静音块 #${sentSilenceChunks}/${silenceChunks}`)
            }
          }, 10)

          return
        }

        // 获取当前块
        const start = sentChunks * chunkSize
        const end = Math.min(start + chunkSize, int16Data.length)
        const chunk = int16Data.slice(start, end)

        // 发送音频数据
        socketRef.current.emit("raw_audio_data", {
          audio: Array.from(chunk)
        })

        sentChunks++

        // 每 10 个块打印一次日志
        if (sentChunks % 10 === 1) {
          console.log(`[Conversation] 🎵 发送真实音频块 #${sentChunks}/${totalChunks}`)
        }
      }, 10)  // 每 10ms 发送一块

      updateStatus("listening")

    } catch (error) {
      console.error("[Conversation] ❌ 发送真实音频失败:", error)
      setError(`发送真实音频失败: ${error}`)
    }
  }, [updateStatus])

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
    sendTestAudio,
    sendRealTestAudio,
  }
}