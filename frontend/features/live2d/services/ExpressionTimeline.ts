/**
 * ExpressionTimeline - 表情时间轴播放引擎
 * 根据时间轴在正确的时间点切换表情
 *
 * Note: This file uses browser-only APIs (requestAnimationFrame, performance)
 * It must only be imported from client components with "use client" directive
 */

import { logger } from '@/shared/utils/logger'

export interface TimelineSegment {
  emotion: string
  time: number      // 开始时间（秒）
  duration: number  // 持续时间（秒）
  intensity: number // 情绪强度 (0.0 - 1.0)，必需字段
}

type ExpressionCallback = (emotion: string, intensity: number) => void

export class ExpressionTimeline {
  private segments: TimelineSegment[]
  private totalDuration: number
  private onExpressionChange: ExpressionCallback
  private startTime: number = 0
  private isPlaying: boolean = false
  private animationFrameId: number | null = null
  private currentEmotion: string = 'neutral'

  constructor(
    segments: TimelineSegment[],
    totalDuration: number,
    onExpressionChange: ExpressionCallback
  ) {
    this.segments = segments.sort((a, b) => a.time - b.time)
    this.totalDuration = totalDuration
    this.onExpressionChange = onExpressionChange
  }

  /**
   * 开始播放时间轴
   * @param startTime 可选的开始时间偏移（秒），默认为当前时间
   */
  play(startTime?: number): void {
    if (this.isPlaying) {
      logger.warn('[ExpressionTimeline] 时间轴已在播放中')
      return
    }

    this.isPlaying = true
    this.startTime = startTime ?? performance.now() / 1000

    logger.debug(
      `[ExpressionTimeline] 开始播放: ${this.segments.length} 个片段, ` +
      `总时长 ${this.totalDuration}s`
    )

    // 立即设置第一个表情
    this.updateExpression(0)

    // 开始动画循环
    this.startAnimationLoop()
  }

  /**
   * 停止播放时间轴
   */
  stop(): void {
    if (!this.isPlaying) {
      return
    }

    this.isPlaying = false

    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId)
      this.animationFrameId = null
    }

    logger.debug('[ExpressionTimeline] 停止播放')
  }

  /**
   * 重置时间轴状态
   */
  reset(): void {
    this.stop()
    this.currentEmotion = 'neutral'
  }

  /**
   * 动画循环
   */
  private startAnimationLoop(): void {
    const loop = () => {
      if (!this.isPlaying) {
        return
      }

      const currentTime = performance.now() / 1000
      const elapsed = currentTime - this.startTime

      // 检查是否播放完成
      if (elapsed >= this.totalDuration) {
        this.stop()
        return
      }

      // 更新表情
      this.updateExpression(elapsed)

      // 继续循环
      this.animationFrameId = requestAnimationFrame(loop)
    }

    this.animationFrameId = requestAnimationFrame(loop)
  }

  /**
   * 根据当前时间更新表情
   */
  private updateExpression(elapsedTime: number): void {
    // 查找当前时间对应的表情
    let targetEmotion = 'neutral'
    let targetIntensity = 1.0  // 默认强度

    for (const segment of this.segments) {
      if (elapsedTime >= segment.time && elapsedTime < segment.time + segment.duration) {
        targetEmotion = segment.emotion
        targetIntensity = segment.intensity  // 使用强度值
        break
      }
    }

    // 如果表情变化，触发回调
    if (targetEmotion !== this.currentEmotion) {
      logger.debug(
        `[ExpressionTimeline] 表情切换: ${this.currentEmotion} -> ${targetEmotion} ` +
        `(intensity: ${targetIntensity.toFixed(2)})`
      )
      this.currentEmotion = targetEmotion
      this.onExpressionChange(targetEmotion, targetIntensity)  // 传递强度值
    }
  }

  /**
   * 获取当前表情
   */
  getCurrentEmotion(): string {
    return this.currentEmotion
  }

  /**
   * 是否正在播放
   */
  getIsPlaying(): boolean {
    return this.isPlaying
  }
}

/**
 * 便捷函数：创建并播放时间轴
 */
export function playExpressionTimeline(
  segments: TimelineSegment[],
  totalDuration: number,
  onExpressionChange: ExpressionCallback
): ExpressionTimeline {
  const timeline = new ExpressionTimeline(
    segments,
    totalDuration,
    onExpressionChange
  )
  timeline.play()
  return timeline
}
