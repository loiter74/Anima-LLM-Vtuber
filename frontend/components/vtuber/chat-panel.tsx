"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { MessageSquare, Send, Bot, User, Wifi, WifiOff } from "lucide-react"
import { getSocket, connectSocket, disconnectSocket } from "@/lib/socket"

interface ChatMessage {
  id: string
  sender: "user" | "ai"
  message: string
  time: string
}

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: "1",
    sender: "ai",
    message: "你好！我是你的 AI 伴侣。今天过得怎么样？",
    time: "14:30",
  },
]

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES)
  const [inputValue, setInputValue] = useState("")
  const [isTyping, setIsTyping] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 获取当前时间字符串
  const getCurrentTime = () => {
    const now = new Date()
    return `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`
  }

  // 添加消息
  const addMessage = useCallback((sender: "user" | "ai", message: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        sender,
        message,
        time: getCurrentTime(),
      },
    ])
  }, [])

  // 初始化 Socket.IO 连接
  useEffect(() => {
    const socket = getSocket()

    // 连接成功
    socket.on("connect", () => {
      console.log("[ChatPanel] 已连接到服务器")
      setIsConnected(true)
    })

    // 断开连接
    socket.on("disconnect", () => {
      console.log("[ChatPanel] 已断开连接")
      setIsConnected(false)
    })

    // 接收 AI 回复
    socket.on("full-text", (data: { type: string; text: string }) => {
      console.log("[ChatPanel] 收到 AI 回复:", data.text)
      setIsTyping(false)
      addMessage("ai", data.text)
    })

    // 连接建立确认
    socket.on("connection-established", (data: { message: string; sid: string }) => {
      console.log("[ChatPanel] 服务器确认连接:", data)
    })

    // 连接到服务器
    connectSocket()

    // 清理
    return () => {
      socket.off("connect")
      socket.off("disconnect")
      socket.off("full-text")
      socket.off("connection-established")
    }
  }, [addMessage])

  // 滚动到底部
  useEffect(() => {
    // ScrollArea 内部的 viewport 元素
    const viewport = scrollRef.current?.querySelector('[data-radix-scroll-area-viewport]')
    if (viewport) {
      viewport.scrollTop = viewport.scrollHeight
    }
  }, [messages, isTyping])

  // 发送消息
  const handleSend = () => {
    if (!inputValue.trim()) return

    const text = inputValue.trim()
    
    // 添加用户消息到界面
    addMessage("user", text)
    setInputValue("")

    // 如果已连接，发送到后端
    if (isConnected) {
      setIsTyping(true)
      const socket = getSocket()
      socket.emit("text_input", { text })
    } else {
      // 未连接时显示提示
      addMessage("ai", "⚠️ 未连接到服务器，请检查后端是否启动")
    }
  }

  // 重连
  const handleReconnect = () => {
    connectSocket()
  }

  return (
    <div className="flex h-full flex-col">
      {/* Chat header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
            <MessageSquare className="size-4 text-primary" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              对话
            </h2>
            <p className="text-xs text-muted-foreground">
              {messages.length} 条消息
            </p>
          </div>
        </div>
        
        {/* 连接状态 */}
        <div className="flex items-center gap-2">
          {isConnected ? (
            <div className="flex items-center gap-1.5 rounded-full bg-green-500/15 px-2.5 py-1">
              <Wifi className="size-3 text-green-500" />
              <span className="text-xs font-medium text-green-500">已连接</span>
            </div>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleReconnect}
              className="flex items-center gap-1.5 rounded-full bg-red-500/15 px-2.5 py-1 hover:bg-red-500/25"
            >
              <WifiOff className="size-3 text-red-500" />
              <span className="text-xs font-medium text-red-500">未连接</span>
            </Button>
          )}
        </div>
      </div>

      {/* Messages - 添加 min-h-0 确保滚动正常工作 */}
      <div className="min-h-0 flex-1">
        <ScrollArea className="h-full" ref={scrollRef}>
          <div className="flex flex-col gap-3 p-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex gap-2.5 ${msg.sender === "user" ? "flex-row-reverse" : "flex-row"}`}
              >
                {/* Avatar */}
                <div
                  className={`flex size-7 shrink-0 items-center justify-center rounded-full ${
                    msg.sender === "ai"
                      ? "bg-primary/10"
                      : "bg-secondary"
                  }`}
                >
                  {msg.sender === "ai" ? (
                    <Bot className="size-3.5 text-primary" />
                  ) : (
                    <User className="size-3.5 text-secondary-foreground" />
                  )}
                </div>

                {/* Message bubble */}
                <div
                  className={`flex max-w-[75%] flex-col gap-1 ${msg.sender === "user" ? "items-end" : "items-start"}`}
                >
                  <div
                    className={`rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed ${
                      msg.sender === "ai"
                        ? "rounded-tl-sm bg-card border border-border text-foreground shadow-sm"
                        : "rounded-tr-sm bg-primary text-primary-foreground"
                    }`}
                  >
                    {msg.message}
                  </div>
                  <span className="px-1 text-[10px] text-muted-foreground">
                    {msg.time}
                  </span>
                </div>
              </div>
            ))}

            {/* Typing indicator */}
            {isTyping && (
              <div className="flex gap-2.5">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                  <Bot className="size-3.5 text-primary" />
                </div>
                <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 shadow-sm">
                  <div className="flex items-center gap-1">
                    {[0, 1, 2].map((i) => (
                      <div
                        key={i}
                        className="size-1.5 rounded-full bg-muted-foreground/40 animate-pulse"
                        style={{ animationDelay: `${i * 0.2}s` }}
                      />
                    ))}
                  </div>
                  <span className="ml-1 text-[11px] text-muted-foreground">
                    正在输入...
                  </span>
                </div>
              </div>
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Input area */}
      <div className="border-t border-border p-3">
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            handleSend()
          }}
        >
          <Input
            placeholder="输入消息..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            className="h-9 text-xs"
            disabled={isTyping}
          />
          <Button
            type="submit"
            size="sm"
            className="h-9 w-9 shrink-0 p-0"
            disabled={isTyping || !inputValue.trim()}
          >
            <Send className="size-3.5" />
            <span className="sr-only">发送消息</span>
          </Button>
        </form>
      </div>
    </div>
  )
}