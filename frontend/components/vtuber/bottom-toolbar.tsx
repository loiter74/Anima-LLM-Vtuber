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
} from "lucide-react"

export function BottomToolbar() {
  const [micOn, setMicOn] = useState(true)
  const [volume, setVolume] = useState([75])
  const [speechRate, setSpeechRate] = useState([1.0])

  return (
    <div className="flex items-center justify-between border-t border-border bg-card px-4 py-3">
      {/* Left section - Mic & Audio */}
      <div className="flex items-center gap-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={micOn ? "default" : "secondary"}
              size="sm"
              className="h-9 gap-2 px-4"
              onClick={() => setMicOn(!micOn)}
            >
              {micOn ? (
                <Mic className="size-4" />
              ) : (
                <MicOff className="size-4" />
              )}
              <span className="text-xs font-medium">
                {micOn ? "Mic On" : "Mic Off"}
              </span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {micOn ? "Mute microphone" : "Unmute microphone"}
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
          <span className="text-xs text-muted-foreground">AI Model Active</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Gauge className="size-3.5 text-accent-foreground" />
          <span className="text-xs text-muted-foreground">Latency 28ms</span>
        </div>
      </div>

      {/* Right section - Settings */}
      <div className="flex items-center gap-2">
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="secondary" size="sm" className="h-9 gap-2 px-4">
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
