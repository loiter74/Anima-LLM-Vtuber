"use client"

/**
 * Live2D Viewer Component
 * 显示 Live2D 角色并处理基于情感的表情系统
 *
 * Note: 使用 pixi-live2d-display/cubism4 导入（内置 SDK）
 */

import { useEffect, useRef, useCallback, useImperativeHandle, forwardRef, useState } from 'react'
import { useLive2D } from '@/features/live2d'
import { logger } from '@/shared/utils/logger'
import { ArrowUp, ArrowDown, ArrowLeft, ArrowRight, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'

export interface Live2DViewerRef {
  adjustPosition: (offsetX: number, offsetY: number) => void
  resetPosition: () => void
}

export interface Live2DViewerProps {
  modelPath?: string
  scale?: number
  position?: { x: number; y: number }
  enabled?: boolean
  className?: string
  /** 初始 Y 轴偏移（负值向上移动头部） */
  initialYOffset?: number
  /** 是否显示位置调整控制 */
  showPositionControls?: boolean
}

export interface Live2DViewerProps {
  modelPath?: string
  scale?: number
  position?: { x: number; y: number }
  enabled?: boolean
  className?: string
  /** 初始 Y 轴偏移（负值向上） */
  initialYOffset?: number
}

/**
 * Live2D 角色查看器组件
 *
 * 新的表情系统：
 * - 基于 LLM 生成的情感标签（[happy], [sad], [angry] 等）
 * - 自动从 audio:with:expression 事件同步表情时间轴
 * - 支持口型同步动画
 * - 支持手动位置调整
 *
 * @example
 * ```tsx
 * <Live2DViewer
 *   modelPath="/live2d/hiyori/Hiyori.model3.json"
 *   scale={1.0}
 *   initialYOffset={-50}
 *   enabled={true}
 *   showPositionControls={true}
 * />
 * ```
 */
export const Live2DViewer = forwardRef<Live2DViewerRef, Live2DViewerProps>(({
  modelPath = '/live2d/hiyori/Hiyori.model3.json',
  scale = 1.0,
  position = { x: 0, y: 0 },
  enabled = true,
  className = '',
  initialYOffset = 120, // 默认向下偏移，适合VTuber头像显示（头部在画面上方）
  showPositionControls = true,
}, ref) => {
  const [isControlsVisible, setIsControlsVisible] = useState(false)
  const controlsRef = useRef<HTMLDivElement>(null)

  // 使用 useCallback 稳定化函数引用，避免 useEffect 重复触发
  const handleExpressionChange = useCallback((expr: string) => {
    logger.debug(`[Live2DViewer] 表情变化: ${expr}`)
  }, [])

  const handleError = useCallback((err: Error) => {
    logger.error('[Live2DViewer] 错误:', err)
  }, [])

  const { canvasRef, isLoaded, error, adjustPosition } = useLive2D({
    modelPath,
    scale,
    position,
    enabled,
    onExpressionChange: handleExpressionChange,
    onError: handleError,
  })

  // 暴露方法给父组件
  useImperativeHandle(ref, () => ({
    adjustPosition: (offsetX: number, offsetY: number) => {
      adjustPosition(offsetX, offsetY)
    },
    resetPosition: () => {
      // 重置位置会触发自动居中
      const service = (window as any).__live2dService
      if (service) {
        const canvas = canvasRef.current
        if (canvas) {
          service.handleResize()
        }
      }
    },
  }))

  // 应用初始 Y 轴偏移
  useEffect(() => {
    if (isLoaded && initialYOffset !== 0) {
      const timer = setTimeout(() => {
        adjustPosition(0, initialYOffset)
        logger.info(`[Live2DViewer] 应用初始 Y 轴偏移: ${initialYOffset}px`)
      }, 100) // 延迟一点，确保模型已加载

      return () => clearTimeout(timer)
    }
  }, [isLoaded, initialYOffset, adjustPosition])

  const handlePositionAdjust = (offsetX: number, offsetY: number) => {
    adjustPosition(offsetX, offsetY)
  }

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

      {/* 位置调整控制面板 */}
      {showPositionControls && isLoaded && (
        <>
          {/* 切换按钮 */}
          <Button
            size="sm"
            variant="outline"
            className="absolute top-2 right-2 size-8 p-0 rounded-full opacity-50 hover:opacity-100 transition-opacity"
            onClick={() => setIsControlsVisible(!isControlsVisible)}
            title="调整位置"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="size-4"
            >
              <circle cx="12" cy="12" r="3" />
              <path d="M12 9V3" />
              <path d="M12 15v6" />
              <path d="M9 12H3" />
              <path d="M15 12h6" />
            </svg>
          </Button>

          {/* 控制面板 */}
          {isControlsVisible && (
            <div
              ref={controlsRef}
              className="absolute top-12 right-2 bg-card/95 backdrop-blur-sm rounded-lg border border-border shadow-lg p-2"
            >
              <div className="grid grid-cols-3 gap-1">
                {/* 上 */}
                <div></div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="size-7 p-0"
                  onClick={() => handlePositionAdjust(0, -10)}
                  title="向上"
                >
                  <ArrowUp className="size-3" />
                </Button>
                <div></div>

                {/* 左 */}
                <Button
                  size="sm"
                  variant="ghost"
                  className="size-7 p-0"
                  onClick={() => handlePositionAdjust(-10, 0)}
                  title="向左"
                >
                  <ArrowLeft className="size-3" />
                </Button>

                {/* 重置 */}
                <Button
                  size="sm"
                  variant="ghost"
                  className="size-7 p-0"
                  onClick={() => {
                    const service = (window as any).__live2dService
                    if (service && canvasRef.current) {
                      service.handleResize()
                    }
                  }}
                  title="重置位置"
                >
                  <RotateCcw className="size-3" />
                </Button>

                {/* 右 */}
                <Button
                  size="sm"
                  variant="ghost"
                  className="size-7 p-0"
                  onClick={() => handlePositionAdjust(10, 0)}
                  title="向右"
                >
                  <ArrowRight className="size-3" />
                </Button>

                {/* 下 */}
                <div></div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="size-7 p-0"
                  onClick={() => handlePositionAdjust(0, 10)}
                  title="向下"
                >
                  <ArrowDown className="size-3" />
                </Button>
                <div></div>
              </div>

              <div className="text-[10px] text-muted-foreground text-center mt-1">
                调整位置
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
})

Live2DViewer.displayName = 'Live2DViewer'
