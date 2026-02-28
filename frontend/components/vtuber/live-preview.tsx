"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip"
import { Maximize2, Minimize2, Video, VideoOff } from "lucide-react"
import { useConversationStore } from "@/features/conversation/stores/conversationStore"
import { useTimer } from "@/hooks/use-timer"
import { formatTime } from "@/shared/utils/format"
import { Live2DViewer } from "@/components/vtuber/live2d-viewer"

// 创建稳定的 position 对象，避免每次渲染都创建新引用
const STABLE_POSITION = { x: 0, y: 0 }

export function LivePreview() {
  const [isLive, setIsLive] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showLive2D, setShowLive2D] = useState(true)

  // 直接从 store 读取状态（避免调用 useConversation）
  const status = useConversationStore((state) => state.status)

  // 根据真实状态判断是否正在说话
  const isSpeaking = status === "speaking"

  // 使用 useTimer hook
  const { elapsedTime } = useTimer({ interval: 1000, autoStart: isLive })

  return (
    <div className="flex h-full flex-col">
      {/* Header bar - 响应式优化 */}
      <div className="flex items-center justify-between border-b border-border px-3 md:px-4 py-2 md:py-3">
        <div className="flex items-center gap-2 md:gap-3">
          <div className="flex size-7 md:size-8 items-center justify-center rounded-lg bg-primary">
            <Video className="size-3.5 md:size-4 text-primary-foreground" />
          </div>
          <div>
            <h2 className="text-xs md:text-sm font-semibold text-foreground">
              Live2D Preview
            </h2>
            <p className="text-[10px] md:text-xs text-muted-foreground">
              Status: {status}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 md:gap-2">
          {isLive && (
            <Badge className="border-none bg-destructive font-mono text-[9px] md:text-[10px] px-1.5 md:px-2 py-0.5 text-primary-foreground animate-pulse">
              ACTIVE
            </Badge>
          )}
          <span className="font-mono text-[10px] md:text-xs text-muted-foreground hidden sm:inline">
            {formatTime(elapsedTime)}
          </span>
        </div>
      </div>

      {/* Live2D Canvas Container */}
      <div className="relative flex-1 overflow-hidden bg-foreground/[0.02]">
        {showLive2D ? (
          <Live2DViewer
            modelPath="/live2d/hiyori/Hiyori.model3.json"
            scale={1.0}
            position={STABLE_POSITION}
            enabled={isLive}
            className="w-full h-full"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-muted-foreground">Live2D 已禁用</p>
              <p className="text-xs text-muted-foreground/60 mt-1">点击下方按钮启用</p>
            </div>
          </div>
        )}

        {/* Status indicators overlay - 响应式优化 */}
        {isLive && (
          <div className="absolute bottom-4 md:bottom-6 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 pointer-events-none">
            {/* Speaking indicator */}
            {isSpeaking && (
              <div className="flex items-center gap-0.5 rounded-full bg-card/95 backdrop-blur-sm px-2 md:px-3 py-1 md:py-1.5 shadow-md border border-border">
                {[1, 2, 3, 4, 5].map((i) => (
                  <div
                    key={i}
                    className="w-0.5 rounded-full bg-accent animate-pulse"
                    style={{
                      height: `${6 + Math.random() * 10}px`,
                      animationDelay: `${i * 0.08}s`,
                      animationDuration: `${0.4 + i * 0.08}s`,
                    }}
                  />
                ))}
                <span className="ml-1 md:ml-2 text-[9px] md:text-[10px] font-medium text-muted-foreground">
                  Speaking...
                </span>
              </div>
            )}

            {/* Processing indicator */}
            {(status === "processing" || status === "idle") && !isSpeaking && (
              <div className="flex items-center gap-1 md:gap-1.5 rounded-full bg-card/95 backdrop-blur-sm px-2 md:px-3 py-1 md:py-1.5 shadow-md border border-border">
                <div className="size-1.5 rounded-full bg-yellow-500 animate-ping" />
                <span className="text-[9px] md:text-[10px] font-medium text-muted-foreground">
                  {status === "processing" ? "处理中..." : "待机中"}
                </span>
              </div>
            )}

            {/* Listening indicator */}
            {status === "listening" && !isSpeaking && (
              <div className="flex items-center gap-1 md:gap-1.5 rounded-full bg-card/95 backdrop-blur-sm px-2 md:px-3 py-1 md:py-1.5 shadow-md border border-border">
                <div className="relative flex size-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75"></span>
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500"></span>
                </div>
                <span className="text-[9px] md:text-[10px] font-medium text-muted-foreground">
                  录音中...
                </span>
              </div>
            )}

            {/* Error indicator */}
            {status === "error" && !isSpeaking && (
              <div className="flex items-center gap-1 md:gap-1.5 rounded-full bg-card/95 backdrop-blur-sm px-2 md:px-3 py-1 md:py-1.5 shadow-md border border-destructive/50">
                <div className="size-2 rounded-full bg-destructive" />
                <span className="text-[9px] md:text-[10px] font-medium text-destructive">
                  错误
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Control bar - 响应式优化 */}
      <div className="flex items-center justify-between border-t border-border px-3 md:px-4 py-2 md:py-2.5">
        <div className="flex items-center gap-1 md:gap-1.5">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-[10px] md:text-xs px-1.5 md:px-2.5"
            onClick={() => setShowLive2D(!showLive2D)}
          >
            {showLive2D ? "隐藏" : "显示"}
            <span className="hidden sm:inline ml-1">Live2D</span>
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="size-7 p-0"
                onClick={() => setIsLive(!isLive)}
              >
                {isLive ? (
                  <Video className="size-3.5 text-accent-foreground" />
                ) : (
                  <VideoOff className="size-3.5 text-muted-foreground" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{isLive ? "Stop" : "Start"}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="size-7 p-0"
                onClick={() => setIsFullscreen(!isFullscreen)}
              >
                {isFullscreen ? (
                  <Minimize2 className="size-3.5" />
                ) : (
                  <Maximize2 className="size-3.5" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
    </div>
  )
}
