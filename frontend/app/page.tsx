"use client"

import { LivePreview } from "@/components/vtuber/live-preview"
import { ChatPanel } from "@/components/vtuber/chat-panel"
import { BottomToolbar } from "@/components/vtuber/bottom-toolbar"
import { useConnectionStore } from "@/features/connection/stores/connectionStore"
import { Bot, Zap, Loader2 } from "lucide-react"

function PageContent() {
  // 直接从 store 读取连接状态（避免调用 useConversation 导致重复初始化）
  const status = useConnectionStore((state) => state.status)
  const isConnected = status === 'connected'

  return (
    <div className="flex h-screen flex-col bg-background">
      {/* Top navigation bar */}
      <header className="flex items-center justify-between border-b border-border bg-card px-4 md:px-5 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary">
            <Bot className="size-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-foreground">
              AI VTuber Console
            </h1>
            <p className="text-[10px] text-muted-foreground">
              Private AI Companion
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* 直接在这里渲染连接状态（移除 ConnectionStatus 组件） */}
          {isConnected ? (
            <div className="flex items-center gap-1.5 rounded-full bg-green-500/15 px-2.5 py-1">
              <Zap className="size-3 text-green-500" />
              <span className="text-xs font-medium text-green-500">
                Connected
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 rounded-full bg-yellow-500/15 px-2.5 py-1">
              <Loader2 className="size-3 text-yellow-500 animate-spin" />
              <span className="text-xs font-medium text-yellow-500">
                Connecting...
              </span>
            </div>
          )}
        </div>
      </header>

      {/* Main content area - 响应式布局 */}
      <main className="flex flex-1 overflow-hidden flex-col lg:flex-row">
        {/* Left - Live2D Preview */}
        <section className="flex-1 border-b lg:border-b-0 lg:border-r border-border bg-card min-h-[50vh] lg:min-h-0">
          <LivePreview />
        </section>

        {/* Right - Chat Panel */}
        <aside className="flex w-full lg:w-[380px] xl:w-[420px] shrink-0 flex-col bg-card h-[50vh] lg:h-auto">
          <ChatPanel />
        </aside>
      </main>

      {/* Bottom Toolbar */}
      <BottomToolbar />
    </div>
  )
}

export default function VTuberConsolePage() {
  // 移除 ConversationProvider 包装（直接使用 PageContent）
  return <PageContent />
}
