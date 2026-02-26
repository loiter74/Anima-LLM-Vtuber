"use client"

/**
 * Live2D React Hook
 * 提供 Live2D 模型加载、表情控制和唇同步功能
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { Live2DService } from '../services/Live2DService'
import { LipSyncEngine } from '../services/LipSyncEngine'
import { logger } from '@/shared/utils/logger'
import type { Live2DModelConfig } from '../types'
import type { TimelineSegment } from '../services/ExpressionTimeline'

export interface UseLive2DOptions {
  modelPath: string
  scale?: number
  position?: { x: number; y: number }
  enabled?: boolean
  lipSyncEnabled?: boolean
  onExpressionChange?: (expression: string) => void
  onError?: (error: Error) => void
}

export function useLive2D(options: UseLive2DOptions) {
  const {
    modelPath,
    scale = 0.5,
    position = { x: 0, y: 0 },
    enabled = true,
    lipSyncEnabled = true,
    onExpressionChange,
    onError,
  } = options

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const serviceRef = useRef<Live2DService | null>(null)
  const lipSyncRef = useRef<LipSyncEngine | null>(null)
  const audioElementRef = useRef<HTMLAudioElement | null>(null)

  const [isLoaded, setIsLoaded] = useState(false)
  const [currentExpression, setCurrentExpression] = useState('idle')
  const [error, setError] = useState<Error | null>(null)
  const [isSpeaking, setIsSpeaking] = useState(false)

  // 使用 ref 存储最新的回调函数，避免因为回调变化而重新初始化
  const onExpressionChangeRef = useRef(onExpressionChange)
  const onErrorRef = useRef(onError)

  // 更新 ref 引用
  useEffect(() => {
    onExpressionChangeRef.current = onExpressionChange
    onErrorRef.current = onError
  }, [onExpressionChange, onError])

  // 初始化 Live2D 服务
  useEffect(() => {
    if (!enabled || !canvasRef.current) return

    const canvas = canvasRef.current
    const config: Live2DModelConfig = {
      path: modelPath,
      scale,
      position,
    }

    const service = new Live2DService(canvas, config)
    serviceRef.current = service

    // 订阅事件
    service.on('model:loaded', () => {
      logger.info('[useLive2D] 模型加载成功')
      setIsLoaded(true)
      setError(null)

      // 设置表情映射（基于情感内容）
      // Haru 模型的 idle 动作组有多个 motion，我们需要映射情感名称到 motion index
      const emotionMap: Record<string, number> = {
        neutral: 0,
        happy: 3,    // 假设 motion 3 是开心的表情
        sad: 1,      // 假设 motion 1 是难过的表情
        angry: 2,    // 假设 motion 2 是生气的表情
        surprised: 4, // 假设 motion 4 是惊讶的表情
        thinking: 5,  // 假设 motion 5 是思考的表情
      }
      service.setEmotionMap(emotionMap)
      logger.info('[useLive2D] 表情映射已设置:', emotionMap)
    })

    service.on('model:error', (err: Error) => {
      logger.error('[useLive2D] 模型加载失败:', err)
      setError(err)
      setIsLoaded(false)
      onErrorRef.current?.(err)
    })

    service.on('expression:change', (expression: string) => {
      setCurrentExpression(expression)
      onExpressionChangeRef.current?.(expression)
    })

    // 加载模型
    service.loadModel().catch((err) => {
      logger.error('[useLive2D] 模型加载失败:', err)
    })

    // 清理
    return () => {
      service.destroy()
      setIsLoaded(false)
      setCurrentExpression('neutral')
    }
  }, [modelPath, scale, position, enabled]) // 移除 onExpressionChange 和 onError

  // 设置表情
  const setExpression = useCallback((expression: string) => {
    if (!enabled || !serviceRef.current) return
    serviceRef.current.setExpression(expression)

    // 更新说话状态
    if (expression === 'speaking') {
      setIsSpeaking(true)
    } else {
      setIsSpeaking(false)
    }
  }, [enabled])

  // 连接唇同步
  const connectLipSync = useCallback(async (audioElement: HTMLAudioElement) => {
    if (!lipSyncEnabled || !isLoaded) return

    try {
      audioElementRef.current = audioElement

      // 创建唇同步引擎
      const lipSyncEngine = new LipSyncEngine((value: number) => {
        // 更新嘴部动作
        serviceRef.current?.setMouthOpen(value)
      })

      await lipSyncEngine.connect(audioElement)
      lipSyncRef.current = lipSyncEngine

      logger.info('[useLive2D] 唇同步已连接')
    } catch (error) {
      logger.error('[useLive2D] 唇同步连接失败:', error)
    }
  }, [lipSyncEnabled, isLoaded])

  // 断开唇同步
  const disconnectLipSync = useCallback(() => {
    if (lipSyncRef.current) {
      lipSyncRef.current.disconnect()
      lipSyncRef.current = null
      logger.info('[useLive2D] 唇同步已断开')
    }
  }, [])

  /**
   * 播放音频 + 表情（完整协调）
   * @param audioData base64 编码的音频数据
   * @param volumes 音量包络数组
   * @param segments 表情时间轴片段
   * @param totalDuration 总时长（秒）
   * @param format 音频格式
   */
  const playAudioWithExpressions = useCallback((
    audioData: string,
    volumes: number[],
    segments: TimelineSegment[],
    totalDuration: number,
    format: string = 'mp3'
  ) => {
    if (!serviceRef.current || !isLoaded) {
      logger.warn('[useLive2D] Live2D 未加载，无法播放')
      return
    }

    try {
      // 1. 播放表情时间轴
      serviceRef.current.playTimeline(segments, totalDuration)

      // 2. 创建音频元素并播放
      const audio = new Audio()
      audio.src = `data:audio/${format};base64,${audioData}`

      // 3. 创建唇同步引擎并使用预计算的音量包络
      const lipSyncEngine = new LipSyncEngine((value: number) => {
        serviceRef.current?.setMouthOpen(value)
      })

      // 音频播放时开始口型同步
      audio.addEventListener('play', () => {
        lipSyncEngine.startWithVolumes(volumes, 50) // 50 Hz 采样率
        setIsSpeaking(true)
      })

      // 音频结束时清理
      audio.addEventListener('ended', () => {
        lipSyncEngine.stopVolumes()
        setIsSpeaking(false)
        serviceRef.current?.stopTimeline()
        serviceRef.current?.setExpression('neutral')
      })

      // 播放音频
      audio.play().catch((error) => {
        logger.error('[useLive2D] 音频播放失败:', error)
      })

      logger.info('[useLive2D] 开始播放音频 + 表情')
    } catch (error) {
      logger.error('[useLive2D] 播放失败:', error)
    }
  }, [isLoaded])

  // 监听 audio:with:expression 事件（从 ConversationService 发送）
  useEffect(() => {
    const handleAudioWithExpression = (event: Event) => {
      const customEvent = event as CustomEvent<{
        audio_data: string
        format: string
        volumes: number[]
        expressions: {
          segments: TimelineSegment[]
          total_duration: number
        }
        text: string
        seq: number
      }>

      const { audio_data, format, volumes, expressions } = customEvent.detail

      logger.info('[useLive2D] 收到 audio:with:expression 事件')
      logger.debug(`  - 音频格式: ${format}`)
      logger.debug(`  - 音量采样: ${volumes.length} 个`)
      logger.debug(`  - 表情片段: ${expressions.segments.length} 个`)
      logger.debug(`  - 总时长: ${expressions.total_duration}s`)

      // 调用播放方法
      playAudioWithExpressions(
        audio_data,
        volumes,
        expressions.segments,
        expressions.total_duration,
        format
      )
    }

    window.addEventListener('audio:with:expression', handleAudioWithExpression)

    return () => {
      window.removeEventListener('audio:with:expression', handleAudioWithExpression)
    }
  }, [playAudioWithExpressions])

  return {
    canvasRef,
    isLoaded,
    currentExpression,
    isSpeaking,
    error,
    setExpression,
    connectLipSync,
    disconnectLipSync,
    playAudioWithExpressions,
  }
}
