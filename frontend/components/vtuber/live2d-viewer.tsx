"use client"

/**
 * Live2D Viewer Component
 * 显示 Live2D 角色并处理基于情感的表情系统
 *
 * Note: 使用 pixi-live2d-display/cubism4 导入（内置 SDK）
 */

import { useEffect, useRef, useCallback } from 'react'
import { useLive2D } from '@/features/live2d'
import { logger } from '@/shared/utils/logger'

export interface Live2DViewerProps {
  modelPath?: string
  scale?: number
  position?: { x: number; y: number }
  enabled?: boolean
  className?: string
}

/**
 * Live2D 角色查看器组件
 *
 * 新的表情系统：
 * - 基于 LLM 生成的情感标签（[happy], [sad], [angry] 等）
 * - 自动从 audio:with:expression 事件同步表情时间轴
 * - 支持口型同步动画
 * - 自动居中并应用 VTuber 头像布局
 *
 * @example
 * ```tsx
 * <Live2DViewer
 *   modelPath="/live2d/hiyori/Hiyori.model3.json"
 *   scale={1.0}
 *   enabled={true}
 * />
 * ```
 */
export function Live2DViewer({
  modelPath = '/live2d/hiyori/Hiyori.model3.json',
  scale = 1.0,
  position = { x: 0, y: 0 },
  enabled = true,
  className = '',
}: Live2DViewerProps) {
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
    <div className={`relative w-full h-full ${className}`}>
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
    </div>
  )
}
