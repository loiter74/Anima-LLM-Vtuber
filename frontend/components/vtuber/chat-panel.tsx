"use client"

import { useRef, useEffect, useCallback } from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { 
  MessageSquare, 
  Send, 
  Bot, 
  User, 
  Wifi, 
  WifiOff, 
  Mic, 
  MicOff,
  Square,
  Trash2,
  Loader2
} from "lucide-react"
import { ConversationStatus } from "@/hooks/use-conversation"
import { useConversationContext } from "@/contexts/conversation-context"

// 状态徽章颜色
const statusStyles: Record<ConversationStatus, { bg: string; text: string; label: string }> = {
  idle: { bg: "bg-gray-500/15", text: "text-gray-500", label: "空闲" },
  listening: { bg: "bg-blue-500/15", text: "text-blue-500", label: "倾听中" },
  processing: { bg: "bg-yellow-500/15", text: "text-yellow-500", label: "思考中" },
  speaking: { bg: "bg-green-500/15", text: "text-green-500", label: "说话中" },
  interrupted: { bg: "bg-orange-500/15", text: "text-orange-500", label: "已打断" },
  error: { bg: "bg-red-500/15", text: "text-red-500", label: "错误" },
}

export function ChatPanel() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // 使用共享的对话 Context
  const {
    isConnected,
    status,
    messages,
    currentResponse,
    isTyping,
    error,
    connect,
    sendText,
    startRecording,
    stopRecording,
    interrupt,
    clearHistory,
    sendTestAudio,
  } = useConversationContext()

  // 发送消息
  const handleSend = useCallback((text: string) => {
    if (!text.trim()) return
    sendText(text)
    if (inputRef.current) {
      inputRef.current.value = ""
    }
  }, [sendText])

  // 切换录音
  const toggleRecording = useCallback(() => {
    if (status === "listening") {
      stopRecording()
    } else {
      startRecording()
    }
  }, [status, startRecording, stopRecording])

  // 滚动到底部
  useEffect(() => {
    const viewport = scrollRef.current?.querySelector('[data-radix-scroll-area-viewport]')
    if (viewport) {
      viewport.scrollTop = viewport.scrollHeight
    }
  }, [messages, currentResponse, isTyping])

  // 获取当前状态样式
  const statusStyle = statusStyles[status]

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
        
        {/* 状态和控制 */}
        <div className="flex items-center gap-2">
          {/* 状态徽章 */}
          <Badge 
            variant="outline" 
            className={`${statusStyle.bg} ${statusStyle.text} border-0`}
          >
            {statusStyle.label}
          </Badge>
          
          {/* 连接状态 */}
          {isConnected ? (
            <div className="flex items-center gap-1.5 rounded-full bg-green-500/15 px-2.5 py-1">
              <Wifi className="size-3 text-green-500" />
              <span className="text-xs font-medium text-green-500">已连接</span>
            </div>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={connect}
              className="flex items-center gap-1.5 rounded-full bg-red-500/15 px-2.5 py-1 hover:bg-red-500/25"
            >
              <WifiOff className="size-3 text-red-500" />
              <span className="text-xs font-medium text-red-500">未连接</span>
            </Button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="min-h-0 flex-1">
        <ScrollArea className="h-full" ref={scrollRef}>
          <div className="flex flex-col gap-3 p-4">
            {/* 欢迎消息 */}
            {messages.length === 0 && (
              <div className="flex gap-2.5">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                  <Bot className="size-3.5 text-primary" />
                </div>
                <div className="flex max-w-[75%] flex-col gap-1">
                  <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-3.5 py-2.5 text-[13px] leading-relaxed text-foreground shadow-sm">
                    你好！我是你的 AI 伴侣。今天过得怎么样？
                  </div>
                </div>
              </div>
            )}
            
            {/* 消息列表 */}
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
                    {msg.text}
                  </div>
                  <span className="px-1 text-[10px] text-muted-foreground">
                    {msg.time}
                  </span>
                </div>
              </div>
            ))}

            {/* 流式响应（正在生成） */}
            {currentResponse && (
              <div className="flex gap-2.5">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                  <Bot className="size-3.5 text-primary" />
                </div>
                <div className="flex max-w-[75%] flex-col gap-1">
                  <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-3.5 py-2.5 text-[13px] leading-relaxed text-foreground shadow-sm">
                    {currentResponse}
                    <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-primary" />
                  </div>
                </div>
              </div>
            )}

            {/* Typing indicator */}
            {isTyping && !currentResponse && (
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

            {/* Error message */}
            {error && (
              <div className="flex items-center gap-2 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-500">
                <span>⚠️</span>
                <span>{error}</span>
              </div>
            )}
          </div>
        </ScrollArea>
      </div>

      {/* 工具栏 - 只保留打断和清空历史，麦克风在底部工具栏 */}
      <div className="border-t border-border px-3 py-2">
        <div className="flex items-center justify-between">
          {/* 左侧工具 */}
          <div className="flex items-center gap-1">
            {/* 测试音频按钮 */}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-xs text-purple-500"
              onClick={sendTestAudio}
              disabled={!isConnected || status === "processing"}
              title="发送测试音频（模拟语音）"
            >
              🧪 测试音频
            </Button>

            {/* 打断 */}
            {(status === "speaking" || status === "processing") && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0 text-orange-500"
                onClick={interrupt}
                title="打断"
              >
                <Square className="size-4" />
              </Button>
            )}
            
            {/* 清空历史 */}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
              onClick={clearHistory}
              disabled={messages.length === 0}
              title="清空历史"
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
          
          {/* 状态指示 */}
          {status === "listening" && (
            <div className="flex items-center gap-1.5 text-xs text-red-500">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75"></span>
                <span className="relative inline-flex h-2 w-2 rounded-full bg-red-500"></span>
              </span>
              录音中（请使用底部麦克风按钮）
            </div>
          )}
          
          {status === "processing" && (
            <div className="flex items-center gap-1.5 text-xs text-yellow-500">
              <Loader2 className="size-3 animate-spin" />
              处理中
            </div>
          )}
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-border p-3">
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            const input = inputRef.current
            if (input) {
              handleSend(input.value)
            }
          }}
        >
          <Input
            ref={inputRef}
            placeholder="输入消息..."
            className="h-9 text-xs"
            disabled={isTyping || status === "processing" || status === "listening"}
          />
          <Button
            type="submit"
            size="sm"
            className="h-9 w-9 shrink-0 p-0"
            disabled={isTyping || status === "processing" || status === "listening"}
          >
            <Send className="size-3.5" />
            <span className="sr-only">发送消息</span>
          </Button>
        </form>
      </div>
    </div>
  )
}