"use client"

/**
 * Live2D Viewer Component
 * 显示 Live2D 角色并处理基于情感的表情系统
 *
 * Note: 使用 pixi-live2d-display/cubism4 导入（内置 SDK）
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import { useLive2D } from '@/features/live2d'
import { useLive2DConfig } from '@/features/live2d/hooks/useLive2DConfig'
import { logger } from '@/shared/utils/logger'

export interface Live2DViewerProps {
  modelPath?: string  // 可选，如果不提供则从配置文件读取
  scale?: number      // 可选，如果不提供则从配置文件读取
  position?: { x: number; y: number }  // 可选，如果不提供则从配置文件读取
  enabled?: boolean
  className?: string
  /** Y 轴偏移百分比（0-100），正值向下偏移 */
  yOffsetPercent?: number
  /** 是否显示调试信息 */
  showDebugInfo?: boolean
}

/**
 * Live2D 角色查看器组件
 *
 * 特性：
 * - 基于 LLM 生成的情感标签（[happy], [sad], [angry] 等）
 * - 自动从 audio:with:expression 事件同步表情时间轴
 * - 支持口型同步动画
 * - 可配置的位置偏移
 * - 可选的调试模式
 * - 从配置文件读取默认配置
 *
 * @example
 * ```tsx
 * // 使用配置文件中的默认配置
 * <Live2DViewer enabled={true} />
 *
 * // 覆盖部分配置
 * <Live2DViewer
 *   modelPath="/live2d/hiyori/Hiyori.model3.json"
 *   enabled={true}
 * />
 *
 * // 开启调试模式
 * <Live2DViewer
 *   enabled={true}
 *   showDebugInfo={true}
 * />
 * ```
 */
export function Live2DViewer({
  modelPath,
  scale,
  position,
  enabled = true,
  className = '',
  yOffsetPercent,
  showDebugInfo = false,
}: Live2DViewerProps) {
  // 加载配置
  const { config, loading: configLoading } = useLive2DConfig()

  // ❗ 必须在所有 Hooks 调用之后才能进行条件返回
  const [debugInfo, setDebugInfo] = useState({
    containerWidth: 0,
    containerHeight: 0,
    modelX: 0,
    modelY: 0,
  })

  const containerRef = useRef<HTMLDivElement>(null)

  // 使用 useCallback 稳定化函数引用，避免 useEffect 重复触发
  const handleExpressionChange = useCallback((expr: string) => {
    logger.debug(`[Live2DViewer] 表情变化: ${expr}`)
  }, [])

  const handleError = useCallback((err: Error) => {
    logger.error('[Live2DViewer] 错误:', err)
  }, [])

  // 从配置文件获取默认值，props 可以覆盖
  const finalModelPath = modelPath ?? config?.model.path ?? '/live2d/haru/haru_greeter_t03.model3.json'
  const finalScale = scale ?? config?.model.scale ?? 1.0
  const finalPosition = position ?? {
    x: config?.model.position?.x ?? 0,
    y: config?.model.position?.y ?? 0,
  }
  const finalYOffsetPercent = yOffsetPercent ?? config?.model.position?.yOffsetPercent ?? 0
  const finalEnabled = enabled && (config?.enabled ?? true)

  // 使用配置中的唇同步设置（如果可用）
  const lipSyncConfig = config?.lipSync || {
    enabled: true,
    sensitivity: 2.5,
    smoothing: 0.3,
    minThreshold: 0.05,
    maxValue: 1.0,
    useMouthForm: false,
  }

  const { canvasRef, isLoaded, error } = useLive2D({
    modelPath: finalModelPath,
    scale: finalScale,
    position: finalPosition,
    enabled: finalEnabled,
    lipSyncEnabled: lipSyncConfig.enabled,
    lipSyncConfig,
    onExpressionChange: handleExpressionChange,
    onError: handleError,
  })

  // 更新调试信息
  useEffect(() => {
    if (showDebugInfo && isLoaded) {
      const updateDebugInfo = () => {
        const container = containerRef.current
        const service = (window as any).__live2dService

        if (container && service?.model) {
          setDebugInfo({
            containerWidth: container.clientWidth,
            containerHeight: container.clientHeight,
            modelX: service.model.x,
            modelY: service.model.y,
          })
        }
      }

      updateDebugInfo()
      const interval = setInterval(updateDebugInfo, 1000)

      return () => clearInterval(interval)
    }
  }, [showDebugInfo, isLoaded])

  // 应用位置配置（包括缩放）
  useEffect(() => {
    if (isLoaded) {
      const service = (window as any).__live2dService
      if (service) {
        service.setPositionConfig({
          yOffsetPercent: finalYOffsetPercent,
          xOffsetPercent: config?.model.position?.xOffsetPercent ?? 0,
          scaleMultiplier: config?.model.position?.scaleMultiplier ?? 1.0,
        })
      }
    }
  }, [isLoaded, finalYOffsetPercent, config])

  // 配置加载中
  if (configLoading) {
    return (
      <div className={`flex items-center justify-center bg-gray-100 text-gray-500 ${className}`}>
        <div className="text-center">
          <p className="text-sm font-medium">正在加载 Live2D 配置...</p>
        </div>
      </div>
    )
  }

  // Live2D 已禁用
  if (!finalEnabled) {
    return (
      <div className={`flex items-center justify-center bg-gray-100 text-gray-500 ${className}`}>
        <div className="text-center">
          <p className="text-sm font-medium">Live2D 已禁用</p>
          <p className="text-xs mt-1 text-gray-400">点击下方按钮启用</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`flex items-center justify-center bg-gray-900 text-gray-400 ${className}`}>
        <div className="text-center">
          <p className="text-sm">Live2D 加载失败</p>
          <p className="text-xs mt-1">{error.message}</p>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className={`relative w-full h-full ${className}`}>
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ touchAction: 'none' }}
      />
      {!isLoaded && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <div className="text-foreground text-sm md:text-base">正在加载 Live2D 模型...</div>
        </div>
      )}

      {/* 调试信息面板 */}
      {showDebugInfo && (
        <div className="absolute top-2 left-2 bg-black/80 text-white text-xs font-mono p-3 rounded shadow-lg pointer-events-none">
          <div className="font-bold mb-2">Live2D 调试信息</div>
          <div>容器尺寸: {debugInfo.containerWidth} x {debugInfo.containerHeight}</div>
          <div>Y 偏移: {finalYOffsetPercent}%</div>
          <div>模型 X: {debugInfo.modelX.toFixed(0)}</div>
          <div>模型 Y: {debugInfo.modelY.toFixed(0)}</div>
          <div className="mt-2 text-yellow-400">
            提示: 在控制台输入 setPositionConfig 调整位置
          </div>
        </div>
      )}
    </div>
  )
}
