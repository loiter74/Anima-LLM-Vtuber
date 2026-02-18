"use client"

import { useState, useEffect } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip"
import { Maximize2, Minimize2, Video, VideoOff } from "lucide-react"

const EXPRESSIONS = [
  { name: "Neutral", label: "Neutral" },
  { name: "Happy", label: "Happy" },
  { name: "Surprised", label: "Surprised" },
  { name: "Thinking", label: "Thinking" },
]

export function LivePreview() {
  const [isLive, setIsLive] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [currentExpression, setCurrentExpression] = useState("Neutral")
  const [elapsedTime, setElapsedTime] = useState(0)
  const [isSpeaking, setIsSpeaking] = useState(false)

  // Simulate speaking animation
  useEffect(() => {
    if (!isLive) {
      setIsSpeaking(false)
      return
    }
    const interval = setInterval(() => {
      setIsSpeaking((prev) => !prev)
    }, 2000 + Math.random() * 3000)
    return () => clearInterval(interval)
  }, [isLive])

  useEffect(() => {
    if (!isLive) return
    const interval = setInterval(() => {
      setElapsedTime((t) => t + 1)
    }, 1000)
    return () => clearInterval(interval)
  }, [isLive])

  const formatTime = (s: number) => {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    const sec = s % 60
    return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header bar */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary">
            <Video className="size-4 text-primary-foreground" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              Live2D Preview
            </h2>
            <p className="text-xs text-muted-foreground">
              Expression: {currentExpression}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isLive && (
            <Badge className="border-none bg-destructive font-mono text-[10px] px-2 py-0.5 text-primary-foreground animate-pulse">
              ACTIVE
            </Badge>
          )}
          <span className="font-mono text-xs text-muted-foreground">
            {formatTime(elapsedTime)}
          </span>
        </div>
      </div>

      {/* Live2D Canvas Container */}
      <div className="relative flex-1 overflow-hidden bg-foreground/[0.02]">
        {/*
          Live2D Integration Point:
          Mount your Live2D canvas to the div#live2d-canvas below.
          Example with pixi-live2d-display:
            const app = new PIXI.Application({ view: document.getElementById('live2d-canvas') })
        */}
        <div className="absolute inset-0 flex items-center justify-center">
          {/* Live2D canvas placeholder */}
          <div
            id="live2d-canvas"
            className="relative flex size-full items-center justify-center"
          >
            {/* Ambient background effect */}
            <div className="absolute inset-0 bg-gradient-to-b from-primary/[0.03] via-transparent to-accent/[0.03]" />

            {/* Placeholder visual when Live2D is not loaded */}
            <div className="relative flex flex-col items-center gap-4">
              <div className="relative">
                <div className="absolute -inset-16 rounded-full bg-primary/[0.06] blur-3xl" />
                <div className="relative flex size-48 items-center justify-center rounded-full border-2 border-dashed border-border bg-card/50">
                  <div className="flex flex-col items-center gap-2 text-center">
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      className="size-10 text-muted-foreground/50"
                      strokeWidth={1.2}
                    >
                      <rect x="2" y="3" width="20" height="14" rx="2" />
                      <path d="M8 21h8" />
                      <path d="M12 17v4" />
                      <circle cx="12" cy="10" r="2" />
                    </svg>
                    <p className="text-xs font-medium text-muted-foreground/70">
                      Live2D Canvas
                    </p>
                  </div>
                </div>
              </div>
              <p className="text-[11px] text-muted-foreground/50">
                Mount your Live2D model to <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-foreground/60">#live2d-canvas</code>
              </p>
            </div>

            {/* Speaking indicator - visible when model is active */}
            {isLive && isSpeaking && (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2">
                <div className="flex items-center gap-0.5 rounded-full bg-card px-3 py-1.5 shadow-md border border-border">
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
                  <span className="ml-2 text-[10px] font-medium text-muted-foreground">
                    Speaking...
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Expression controls */}
      <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          {EXPRESSIONS.map((exp) => (
            <Button
              key={exp.name}
              variant={currentExpression === exp.name ? "default" : "secondary"}
              size="sm"
              className="h-7 text-xs px-2.5"
              onClick={() => setCurrentExpression(exp.name)}
            >
              {exp.label}
            </Button>
          ))}
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
