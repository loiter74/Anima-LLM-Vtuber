"use client"

/**
 * Live2D React Hook
 * 提供 Live2D 模型加载、表情控制和唇同步功能
 */

import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
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
  /** 唇同步配置（可选，使用默认值） */
  lipSyncConfig?: {
    sensitivity?: number
    smoothing?: number
    minThreshold?: number
    maxValue?: number
    useMouthForm?: boolean
  }
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
    lipSyncConfig = {},
    onExpressionChange,
    onError,
  } = options

  // 提取 lipSyncConfig 的各个值，避免对象引用变化
  const lipSyncSensitivity = lipSyncConfig.sensitivity ?? 1.0
  const lipSyncSmoothing = lipSyncConfig.smoothing ?? 0.3
  const lipSyncMinThreshold = lipSyncConfig.minThreshold ?? 0.05
  const lipSyncMaxValue = lipSyncConfig.maxValue ?? 1.0
  const lipSyncUseMouthForm = lipSyncConfig.useMouthForm ?? false

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

  // 使用 useMemo 确保 position 对象引用稳定
  const stablePosition = useMemo(() => position, [position.x, position.y])

  // 使用 useMemo 创建稳定的 config 对象
  // 依赖数组使用基本类型值，避免对象引用变化
  const config: Live2DModelConfig = useMemo(() => ({
    path: modelPath,
    scale,
    position: stablePosition,
    lipSync: {
      enabled: lipSyncEnabled,
      sensitivity: lipSyncSensitivity,
      smoothing: lipSyncSmoothing,
      minThreshold: lipSyncMinThreshold,
      maxValue: lipSyncMaxValue,
      useMouthForm: lipSyncUseMouthForm,
    },
  }), [
    modelPath,
    scale,
    stablePosition,
    lipSyncEnabled,
    lipSyncSensitivity,
    lipSyncSmoothing,
    lipSyncMinThreshold,
    lipSyncMaxValue,
    lipSyncUseMouthForm,
  ])

  // 更新 ref 引用
  useEffect(() => {
    onExpressionChangeRef.current = onExpressionChange
    onErrorRef.current = onError
  }, [onExpressionChange, onError])

  // 初始化 Live2D 服务
  useEffect(() => {
    if (!enabled || !canvasRef.current) return

    // 使用 ref 防止多次初始化（在 React StrictMode 或快速 remount 时）
    const isInitializingRef = { current: false }
    let cleanup: (() => void) | null = null
    let isCleaningUp = false

    const initializeService = async () => {
      // 防止并发初始化
      if (isInitializingRef.current) {
        logger.warn('[useLive2D] 初始化已在进行中，跳过重复初始化')
        return
      }

      // 防止在清理后仍然初始化
      if (isCleaningUp) {
        logger.debug('[useLive2D] 正在清理，跳过初始化')
        return
      }

      isInitializingRef.current = true

      const canvas = canvasRef.current
      if (!canvas) {
        isInitializingRef.current = false
        return
      }

      logger.info('[useLive2D] 开始初始化 Live2D 服务')

      const service = new Live2DService(canvas, config)
      serviceRef.current = service

      // 订阅事件
      service.on('model:loaded', () => {
        if (isCleaningUp) return
        logger.info('[useLive2D] 模型加载成功')
        setIsLoaded(true)
        setError(null)

        // 设置表情映射（基于情感内容）
        // Hiyori 模型的表情组有多个 expression，我们需要映射情感名称到 expression index
        const emotionMap: Record<string, number> = {
          neutral: 0,
          happy: 3,    // expression 3 是开心的表情
          sad: 1,      // expression 1 是难过的表情
          angry: 2,    // expression 2 是生气的表情
          surprised: 4, // expression 4 是惊讶的表情
          thinking: 5,  // expression 5 是思考的表情
        }
        service.setEmotionMap(emotionMap)
        logger.info('[useLive2D] 表情映射已设置:', emotionMap)
      })

      service.on('model:error', (err: Error) => {
        if (isCleaningUp) return
        logger.error('[useLive2D] 模型加载失败:', err)
        setError(err)
        setIsLoaded(false)
        onErrorRef.current?.(err)
        isInitializingRef.current = false
      })

      service.on('expression:change', (expression: string) => {
        if (isCleaningUp) return
        setCurrentExpression(expression)
        onExpressionChangeRef.current?.(expression)
      })

      // 加载模型
      try {
        await service.loadModel()
        if (!isCleaningUp) {
          logger.info('[useLive2D] Live2D 服务初始化完成')
        }
        isInitializingRef.current = false
      } catch (err) {
        if (!isCleaningUp) {
          logger.error('[useLive2D] 模型加载失败:', err)
        }
        isInitializingRef.current = false
      }
    }

    initializeService()

    // 清理函数 - 等待销毁完成
    cleanup = () => {
      isCleaningUp = true
      isInitializingRef.current = false // 允许新的初始化在清理完成后开始
      const service = serviceRef.current
      if (service) {
        logger.info('[useLive2D] 正在销毁 Live2D 服务')
        service.destroy().then(() => {
          if (!isCleaningUp) return
          logger.info('[useLive2D] Live2D 服务已销毁')
          setIsLoaded(false)
          setCurrentExpression('neutral')
          serviceRef.current = null
        })
      } else {
        setIsLoaded(false)
        setCurrentExpression('neutral')
      }
    }

    return cleanup
  }, [config, enabled]) // 只依赖稳定的 config 和 enabled

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
      const lipSyncEngine = new LipSyncEngine(
        (value: number) => {
          // 更新嘴部动作
          serviceRef.current?.setMouthOpen(value)
        },
        {
          updateInterval: 33, // ~30fps
          enableSmoothing: true,
          smoothingFactor: 0.5,
          volumeMultiplier: 1.0,
        }
      )

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
    logger.info('[useLive2D] ========== playAudioWithExpressions 被调用 ==========')
    logger.info(`[useLive2D] serviceRef.current: ${serviceRef.current ? '存在' : 'null'}`)
    logger.info(`[useLive2D] isLoaded: ${isLoaded}`)
    logger.info(`[useLive2D] 音频数据长度: ${audioData.length}`)
    logger.info(`[useLive2D] 音量采样点数: ${volumes.length}`)
    logger.info(`[useLive2D] 表情片段数: ${segments.length}`)
    logger.info(`[useLive2D] 总时长: ${totalDuration}s`)
    logger.info(`[useLive2D] 格式: ${format}`)

    if (!serviceRef.current || !isLoaded) {
      logger.warn('[useLive2D] Live2D 未加载，无法播放')
      return
    }

    try {
      logger.info('[useLive2D] 步骤 1: 播放表情时间轴')
      // 1. 播放表情时间轴
      serviceRef.current.playTimeline(segments, totalDuration)

      logger.info('[useLive2D] 步骤 2: 创建音频元素')
      // 2. 创建音频元素并播放
      const audio = new Audio()
      audio.src = `data:audio/${format};base64,${audioData}`

      logger.info('[useLive2D] 步骤 3: 创建唇同步引擎')
      // 3. 创建唇同步引擎并使用预计算的音量包络
      const lipSyncEngine = new LipSyncEngine(
        (value: number) => {
          logger.debug(`[useLive2D] 唇同步回调: value=${value.toFixed(3)}`)
          serviceRef.current?.setMouthOpen(value)
        },
        {
          updateInterval: 33, // ~30fps
          enableSmoothing: true,
          smoothingFactor: 0.5,
          volumeMultiplier: 1.2, // 稍微增强嘴部动作
        }
      )

      logger.info('[useLive2D] 步骤 4: 添加事件监听器')
      // 音频播放时开始口型同步
      audio.addEventListener('play', () => {
        logger.info('[useLive2D] ========== 音频 play 事件触发 ==========')
        logger.info(`[useLive2D] 启动唇同步引擎，采样点数: ${volumes.length}`)
        lipSyncEngine.startWithVolumes(volumes, 50) // 50 Hz 采样率
        setIsSpeaking(true)
      })

      audio.addEventListener('playing', () => {
        logger.info('[useLive2D] ========== 音频 playing 事件触发 ==========')
      })

      audio.addEventListener('error', (e) => {
        logger.error('[useLive2D] ========== 音频 error 事件 ==========', e)
      })

      // 音频结束时清理
      audio.addEventListener('ended', () => {
        logger.info('[useLive2D] ========== 音频 ended 事件触发 ==========')
        lipSyncEngine.stopVolumes()
        setIsSpeaking(false)
        serviceRef.current?.stopTimeline()
        serviceRef.current?.setExpression('neutral')
      })

      logger.info('[useLive2D] 步骤 5: 调用 audio.play()')
      // 播放音频
      audio.play().then(() => {
        logger.info('[useLive2D] audio.play() Promise resolved')
      }).catch((error) => {
        logger.error('[useLive2D] audio.play() Promise rejected:', error)
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

      const { audio_data, format, volumes, expressions, text, seq } = customEvent.detail

      logger.info(
        `[useLive2D] 收到 audio_with_expression 事件 (seq: ${seq})`,
        {
          format,
          volumesLength: volumes.length,
          segmentsCount: expressions.segments.length,
          totalDuration: expressions.total_duration,
          textLength: text?.length || 0
        }
      )

      // 验证 intensity 字段
      const segmentsWithIntensity = expressions.segments.filter(seg =>
        'intensity' in seg && typeof seg.intensity === 'number'
      )

      if (segmentsWithIntensity.length !== expressions.segments.length) {
        logger.warn(
          `[useLive2D] 部分 segment 缺少 intensity 字段 ` +
          `(${segmentsWithIntensity.length}/${expressions.segments.length})`
        )
      } else {
        logger.debug(
          `[useLive2D] 所有 segment 包含 intensity 字段 (${expressions.segments.length} 个)`
        )
      }

      // 播放音频和表情
      const startTime = performance.now()

      playAudioWithExpressions(
        audio_data,
        volumes,
        expressions.segments,
        expressions.total_duration,
        format
      )

      const endTime = performance.now()

      logger.info(
        `[useLive2D] 播放完成 (seq: ${seq}, 耗时: ${(endTime - startTime).toFixed(0)}ms)`
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
