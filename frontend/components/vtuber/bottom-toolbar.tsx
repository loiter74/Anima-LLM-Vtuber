"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogDescription,
} from "@/components/ui/dialog"
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip"
import { AudioPlayer } from "@/features/audio/services/AudioPlayer"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Mic,
  MicOff,
  Settings,
  Volume2,
  Cpu,
  Gauge,
  Monitor,
  Globe,
  RefreshCw,
  Bug,
} from "lucide-react"
import { useConversationContext } from "@/contexts/conversation-context"
import { logger, LogLevel } from "@/lib/logger"
import { getStorage, setStorage } from "@/lib/utils/storage"

export function BottomToolbar() {
  const [volume, setVolume] = useState([75])
  const [speechRate, setSpeechRate] = useState([1.0])

  // 日志级别状态
  const [frontendLogLevel, setFrontendLogLevel] = useState<LogLevel>(() => {
    return getStorage<LogLevel>('anima_log_level', LogLevel.INFO)
  })

  const [backendLogLevel, setBackendLogLevel] = useState("INFO")

  // 使用共享的对话 Context
  const { 
    isConnected, 
    status, 
    startRecording, 
    stopRecording 
  } = useConversationContext()
  
  // 麦克风状态：根据录音状态判断
  const isRecording = status === "listening"
  const isProcessing = status === "processing" || status === "speaking"

  // 切换麦克风
  const toggleMic = async () => {
    if (isRecording) {
      stopRecording()
    } else {
      // 🔥🔥🔥 点击麦克风时，立即停止所有正在播放的音频
      logger.debug('[BottomToolbar] 🎤 麦克风按钮被点击，停止所有音频播放')
      console.log('[BottomToolbar] 🎤 麦克风按钮被点击，停止所有音频播放')
      AudioPlayer.stopGlobalAudio()
      logger.debug('[BottomToolbar] ✅ 音频已停止，开始录音')
      console.log('[BottomToolbar] ✅ 音频已停止，开始录音')

      await startRecording()
    }
  }

  return (
    <div className="flex items-center justify-between border-t border-border bg-card px-4 py-3">
      {/* Left section - Mic & Audio */}
      <div className="flex items-center gap-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={isRecording ? "default" : "secondary"}
              size="sm"
              className="h-9 gap-2 px-4"
              onClick={toggleMic}
              disabled={!isConnected || isProcessing}
            >
              {isRecording ? (
                <Mic className="size-4" />
              ) : (
                <MicOff className="size-4" />
              )}
              <span className="text-xs font-medium">
                {isRecording ? "Mic On" : "Mic Off"}
              </span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {!isConnected 
              ? "未连接到服务器" 
              : isProcessing 
                ? "正在处理中..." 
                : isRecording 
                  ? "关闭麦克风" 
                  : "开启麦克风"}
          </TooltipContent>
        </Tooltip>

        <Separator orientation="vertical" className="h-6" />

        <div className="flex items-center gap-2">
          <Volume2 className="size-4 text-muted-foreground" />
          <Slider
            value={volume}
            onValueChange={setVolume}
            max={100}
            step={1}
            className="w-24"
          />
          <span className="w-8 text-right font-mono text-xs text-muted-foreground">
            {volume[0]}%
          </span>
        </div>
      </div>

      {/* Center section - Status */}
      <div className="hidden items-center gap-3 md:flex">
        <div className="flex items-center gap-1.5">
          <Cpu className="size-3.5 text-primary" />
          <span className="text-xs text-muted-foreground">
            {isConnected ? "AI Model Active" : "Disconnected"}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Gauge className="size-3.5 text-accent-foreground" />
          <span className="text-xs text-muted-foreground">
            Status: {status}
          </span>
        </div>
      </div>

      {/* Right section - Settings */}
      <div className="flex items-center gap-2">
        <Dialog>
          <DialogTrigger asChild>
            <Button
              variant="secondary"
              size="sm"
              className="h-9 gap-2 px-4"
              suppressHydrationWarning
            >
              <Settings className="size-4" />
              <span className="text-xs font-medium">Settings</span>
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>Settings</DialogTitle>
              <DialogDescription>
                Configure your AI VTuber voice and Live2D parameters.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-5 py-4">
              {/* Voice Model */}
              <div className="flex flex-col gap-2">
                <Label className="text-sm font-medium text-foreground">
                  Voice Model
                </Label>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="gap-1.5">
                    <Cpu className="size-3" />
                    Neural Voice v2
                  </Badge>
                  <Button variant="ghost" size="sm" className="h-7">
                    <RefreshCw className="size-3" />
                  </Button>
                </div>
              </div>

              {/* Speech Rate */}
              <div className="flex flex-col gap-2">
                <Label className="text-sm font-medium text-foreground">
                  Speech Rate
                </Label>
                <div className="flex items-center gap-3">
                  <Slider
                    value={speechRate}
                    onValueChange={setSpeechRate}
                    min={0.5}
                    max={2.0}
                    step={0.1}
                    className="flex-1"
                  />
                  <span className="w-10 text-right font-mono text-xs text-muted-foreground">
                    {speechRate[0].toFixed(1)}x
                  </span>
                </div>
              </div>

              {/* Toggles */}
              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Monitor className="size-4 text-muted-foreground" />
                    <Label className="text-sm text-foreground">
                      Live2D Motion Tracking
                    </Label>
                  </div>
                  <Switch defaultChecked />
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Globe className="size-4 text-muted-foreground" />
                    <Label className="text-sm text-foreground">
                      Auto Translation
                    </Label>
                  </div>
                  <Switch />
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Volume2 className="size-4 text-muted-foreground" />
                    <Label className="text-sm text-foreground">
                      Noise Suppression
                    </Label>
                  </div>
                  <Switch defaultChecked />
                </div>
              </div>

              {/* Separator */}
              <Separator />

              {/* Log Levels */}
              <div className="flex flex-col gap-3">
                <Label className="text-sm font-medium text-foreground">
                  Log Levels
                </Label>

                {/* Frontend Log Level */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Bug className="size-4 text-muted-foreground" />
                    <Label className="text-sm text-foreground">
                      Frontend
                    </Label>
                  </div>
                  <Select
                    value={frontendLogLevel.toString()}
                    onValueChange={(value) => {
                      const newLevel = parseInt(value, 10) as LogLevel
                      setFrontendLogLevel(newLevel)
                      setStorage('anima_log_level', newLevel)
                      logger.setLevel(newLevel)
                    }}
                  >
                    <SelectTrigger className="w-[120px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={LogLevel.DEBUG.toString()}>Debug</SelectItem>
                      <SelectItem value={LogLevel.INFO.toString()}>Info</SelectItem>
                      <SelectItem value={LogLevel.WARN.toString()}>Warn</SelectItem>
                      <SelectItem value={LogLevel.ERROR.toString()}>Error</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Backend Log Level */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Bug className="size-4 text-muted-foreground" />
                    <Label className="text-sm text-foreground">
                      Backend
                    </Label>
                  </div>
                  <Select
                    value={backendLogLevel}
                    onValueChange={(value) => {
                      setBackendLogLevel(value)
                      // 通过 Socket.IO 发送到后端
                      const socket = (window as any).socket
                      if (socket?.connected) {
                        socket.emit('set_log_level', { level: value })
                      }
                    }}
                  >
                    <SelectTrigger className="w-[120px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="DEBUG">Debug</SelectItem>
                      <SelectItem value="INFO">Info</SelectItem>
                      <SelectItem value="WARNING">Warning</SelectItem>
                      <SelectItem value="ERROR">Error</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Separator */}
              <Separator />

              {/* Live2D Info */}
              <div className="rounded-lg bg-muted p-3">
                <p className="text-xs font-medium text-foreground">
                  Live2D Model Info
                </p>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <div>
                    <p className="text-[10px] text-muted-foreground">
                      Model
                    </p>
                    <p className="text-xs font-medium text-foreground">
                      Default Avatar
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground">
                      Frame Rate
                    </p>
                    <p className="text-xs font-medium text-foreground">
                      60 fps
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground">
                      Renderer
                    </p>
                    <p className="text-xs font-medium text-foreground">
                      WebGL 2.0
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted-foreground">
                      Physics
                    </p>
                    <p className="text-xs font-medium text-foreground">
                      Enabled
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  )
}