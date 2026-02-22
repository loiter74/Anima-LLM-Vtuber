/**
 * Live2D React Hook
 * 提供 Live2D 模型加载、表情控制和唇同步功能
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { Live2DService } from '../services/Live2DService'
import { LipSyncEngine } from '../services/LipSyncEngine'
import { logger } from '@/shared/utils/logger'
import type { Live2DModelConfig } from '../types'

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
    })

    service.on('model:error', (err: Error) => {
      logger.error('[useLive2D] 模型加载失败:', err)
      setError(err)
      setIsLoaded(false)
      onError?.(err)
    })

    service.on('expression:change', (expression: string) => {
      setCurrentExpression(expression)
      onExpressionChange?.(expression)
    })

    // 加载模型
    service.loadModel().catch((err) => {
      logger.error('[useLive2D] 模型加载失败:', err)
    })

    // 清理
    return () => {
      service.destroy()
      setIsLoaded(false)
      setCurrentExpression('idle')
    }
  }, [modelPath, scale, position, enabled, onExpressionChange, onError])

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

  return {
    canvasRef,
    isLoaded,
    currentExpression,
    isSpeaking,
    error,
    setExpression,
    connectLipSync,
    disconnectLipSync,
  }
}
