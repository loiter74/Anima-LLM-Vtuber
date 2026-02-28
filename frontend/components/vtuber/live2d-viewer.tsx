"use client"

/**
 * Live2D Viewer Component
 * 显示 Live2D 角色并处理基于情感的表情系统
 *
 * Note: 使用 pixi-live2d-display/cubism4 导入（内置 SDK）
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import { useLive2D } from '@/features/live2d'
import { logger } from '@/shared/utils/logger'

export interface Live2DViewerProps {
  modelPath?: string
  scale?: number
  position?: { x: number; y: number }
  enabled?: boolean
  className?: string
  /** Y 轴偏移百分比（0-100），正值向下偏移，默认 20% */
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
 *
 * @example
 * ```tsx
 * // 默认 VTuber 头像位置（向下偏移 20%）
 * <Live2DViewer
 *   modelPath="/live2d/hiyori/Hiyori.model3.json"
 *   enabled={true}
 *   yOffsetPercent={20}
 * />
 *
 * // 完全居中
 * <Live2DViewer
 *   modelPath="/live2d/hiyori/Hiyori.model3.json"
 *   enabled={true}
 *   yOffsetPercent={0}
 * />
 *
 * // 开启调试模式
 * <Live2DViewer
 *   modelPath="/live2d/hiyori/Hiyori.model3.json"
 *   enabled={true}
 *   showDebugInfo={true}
 * />
 * ```
 */
export function Live2DViewer({
  modelPath = '/live2d/hiyori/Hiyori.model3.json',
  scale = 1.0,
  position = { x: 0, y: 0 },
  enabled = true,
  className = '',
  yOffsetPercent = 20,
  showDebugInfo = false,
}: Live2DViewerProps) {
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

  const { canvasRef, isLoaded, error } = useLive2D({
    modelPath,
    scale,
    position,
    enabled,
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

  // 应用位置偏移
  useEffect(() => {
    if (isLoaded && yOffsetPercent !== 0) {
      const service = (window as any).__live2dService
      if (service) {
        service.setPositionConfig({ yOffsetPercent })
      }
    }
  }, [isLoaded, yOffsetPercent])

  if (!enabled) {
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
          <div>Y 偏移: {yOffsetPercent}%</div>
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
