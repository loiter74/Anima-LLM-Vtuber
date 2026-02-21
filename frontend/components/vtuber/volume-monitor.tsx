"use client"

import { useEffect, useRef, useState } from "react"
import { Mic, MicOff, Radio, Signal } from "lucide-react"

export function VolumeMonitor() {
  const [volume, setVolume] = useState(0) // 0-100
  const [isRecording, setIsRecording] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [chunksSent, setChunksSent] = useState(0)
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animationRef = useRef<number>()
  const streamRef = useRef<MediaStream | null>(null)

  useEffect(() => {
    // 监听录音状态变化
    const handleRecordingChange = () => {
      const recording = (window as any).__isRecording || false
      setIsRecording(recording)

      if (recording && !streamRef.current) {
        // 开始录音，初始化音量监控
        initVolumeMonitor()
      } else if (!recording && streamRef.current) {
        // 停止录音，清理资源
        cleanup()
      }
    }

    // 监听数据发送状态
    const handleDataSent = () => {
      setChunksSent(prev => prev + 1)
      setIsSending(true)
      setTimeout(() => setIsSending(false), 100)
    }

    // 初始化检查
    handleRecordingChange()

    // 监听全局状态变化
    window.addEventListener('recording-state-changed', handleRecordingChange)
    window.addEventListener('audio-chunk-sent', handleDataSent)

    return () => {
      cleanup()
      window.removeEventListener('recording-state-changed', handleRecordingChange)
      window.removeEventListener('audio-chunk-sent', handleDataSent)
    }
  }, [])

  const initVolumeMonitor = async () => {
    try {
      // 使用与录音相同的音频约束（禁用音量限制）
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        }
      })
      streamRef.current = stream

      const audioContext = new AudioContext({ sampleRate: 16000 })
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.8

      const source = audioContext.createMediaStreamSource(stream)
      source.connect(analyser)

      audioContextRef.current = audioContext
      analyserRef.current = analyser

      updateVolume()
    } catch (err) {
      console.error("[VolumeMonitor] 初始化失败:", err)
    }
  }

  const updateVolume = () => {
    if (!analyserRef.current) return

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(dataArray)

    // 计算平均音量
    const sum = dataArray.reduce((a, b) => a + b, 0)
    const average = sum / dataArray.length

    // 转换为 0-100 范围
    const volumePercent = Math.round((average / 255) * 100)
    setVolume(volumePercent)

    animationRef.current = requestAnimationFrame(updateVolume)
  }

  const cleanup = () => {
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current)
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop())
      streamRef.current = null
    }
    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }
    analyserRef.current = null
    setVolume(0)
  }

  // 获取音量等级颜色
  const getVolumeColor = () => {
    if (volume < 20) return "bg-green-500"
    if (volume < 50) return "bg-yellow-500"
    return "bg-red-500"
  }

  // 获取音量状态文本
  const getVolumeStatus = () => {
    if (volume < 5) return "无声音"
    if (volume < 20) return "音量小"
    if (volume < 50) return "正常"
    return "音量大"
  }

  return (
    <div className="flex items-center gap-3 rounded-lg bg-card border border-border px-4 py-3">
      {/* 录音状态 */}
      <div className="flex items-center gap-2">
        {isRecording ? (
          <div className="flex items-center gap-1.5 rounded-full bg-red-500/15 px-2.5 py-1">
            <Mic className="size-3 text-red-500" />
            <span className="text-xs font-medium text-red-500">录音中</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 rounded-full bg-gray-500/15 px-2.5 py-1">
            <MicOff className="size-3 text-gray-500" />
            <span className="text-xs font-medium text-gray-500">未录音</span>
          </div>
        )}
      </div>

      {/* 音量条 */}
      <div className="flex flex-1 flex-col gap-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>音量</span>
          <span className="font-mono">{volume}%</span>
        </div>
        <div className="relative h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
          <div
            className={`h-full transition-all duration-150 ${getVolumeColor()}`}
            style={{ width: `${volume}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{getVolumeStatus()}</span>
          <span>已发送: {chunksSent} 块</span>
        </div>
      </div>

      {/* 发送指示器 */}
      {isSending && (
        <div className="flex items-center gap-1.5 text-xs text-green-500">
          <Radio className="size-3 animate-pulse" />
          <span>发送中</span>
        </div>
      )}
    </div>
  )
}
