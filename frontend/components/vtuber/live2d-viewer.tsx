/**
 * Live2D Viewer Component
 * 显示 Live2D 角色并根据对话状态更新表情
 */

import { useEffect, useRef } from 'react'
import { useLive2D } from '@/features/live2d'
import { useConversation } from '@/features/conversation/hooks/useConversation'
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
 * @example
 * ```tsx
 * <Live2DViewer
 *   modelPath="/live2d/haru/haru_greeter_t03.model3.json"
 *   scale={0.5}
 *   enabled={true}
 * />
 * ```
 */
export function Live2DViewer({
  modelPath = '/live2d/haru/haru_greeter_t03.model3.json',
  scale = 0.5,
  position = { x: 0, y: 0 },
  enabled = true,
  className = '',
}: Live2DViewerProps) {
  const { expression } = useConversation()

  const { canvasRef, isLoaded, setExpression, error } = useLive2D({
    modelPath,
    scale,
    position,
    enabled,
    onExpressionChange: (expr) => logger.debug(`[Live2DViewer] 表情变化: ${expr}`),
    onError: (err) => logger.error('[Live2DViewer] 错误:', err),
  })

  // 同步对话状态到 Live2D 表情
  useEffect(() => {
    if (isLoaded) {
      setExpression(expression)
    }
  }, [expression, isLoaded, setExpression])

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
        <div className="absolute inset-0 flex items-center justify-center bg-gray-900/50">
          <div className="text-white text-sm">正在加载 Live2D 模型...</div>
        </div>
      )}
    </div>
  )
}
