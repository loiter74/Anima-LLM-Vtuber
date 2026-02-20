import { LivePreview } from "@/components/vtuber/live-preview"
import { ChatPanel } from "@/components/vtuber/chat-panel"
import { BottomToolbar } from "@/components/vtuber/bottom-toolbar"
import { ConversationProvider } from "@/contexts/conversation-context"
import { Bot, Zap } from "lucide-react"

export default function VTuberConsolePage() {
  return (
    <ConversationProvider>
      <div className="flex h-screen flex-col bg-background">
        {/* Top navigation bar */}
        <header className="flex items-center justify-between border-b border-border bg-card px-5 py-2.5">
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
            <div className="flex items-center gap-1.5 rounded-full bg-accent/15 px-2.5 py-1">
              <Zap className="size-3 text-accent-foreground" />
              <span className="text-xs font-medium text-accent-foreground">
                Connected
              </span>
            </div>
          </div>
        </header>

        {/* Main content area */}
        <main className="flex flex-1 overflow-hidden">
          {/* Left - Live2D Preview */}
          <section className="flex-1 border-r border-border bg-card">
            <LivePreview />
          </section>

          {/* Right - Chat Panel */}
          <aside className="flex w-[380px] shrink-0 flex-col bg-card">
            <ChatPanel />
          </aside>
        </main>

        {/* Bottom Toolbar */}
        <BottomToolbar />
      </div>
    </ConversationProvider>
  )
}