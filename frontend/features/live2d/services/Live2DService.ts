/**
 * Live2D 服务
 * 管理 Live2D 模型的加载、渲染和表情控制
 *
 * Note: This file uses browser-only APIs (PIXI.js, window)
 * It must only be imported from client components with "use client" directive
 */

import { EventEmitter } from 'events'
import { logger } from '@/shared/utils/logger'
import type { Live2DExpression, Live2DModelConfig } from '../types'
import { ExpressionTimeline, type TimelineSegment } from './ExpressionTimeline'

export class Live2DService extends EventEmitter {
  private app: any = null  // PIXI.Application
  private model: any = null  // Live2DModel
  private Live2DModel: any = null  // Live2DModel (动态导入)
  private PIXI: any = null  // PIXI (动态导入)
  private currentExpression: string = 'neutral'
  private canvas: HTMLCanvasElement
  private config: Live2DModelConfig
  private emotionMap: Record<string, number> = {}
  private currentTimeline: ExpressionTimeline | null = null
  private isInitialized: boolean = false

  constructor(canvas: HTMLCanvasElement, config: Live2DModelConfig) {
    super()
    this.canvas = canvas
    this.config = config
  }

  /**
   * 动态加载 Live2D 库
   * 只在客户端执行，避免 SSR 问题
   */
  private async loadLibraries(): Promise<void> {
    if (this.isInitialized) return

    if (typeof window === 'undefined') {
      logger.warn('[Live2DService] Running in SSR mode, skipping initialization')
      return
    }

    try {
      logger.info('[Live2DService] Loading PIXI and Live2D libraries...')

      // 动态导入 PIXI
      const pixiModule = await import('pixi.js')
      this.PIXI = pixiModule

      // 动态导入 cubism4 版本
      const live2dModule = await import('pixi-live2d-display/cubism4')
      this.Live2DModel = live2dModule.Live2DModel

      // 注册 Ticker
      this.Live2DModel.registerTicker(pixiModule.Ticker)

      logger.info('[Live2DService] ✅ All libraries loaded')
      this.isInitialized = true
    } catch (error) {
      logger.error('[Live2DService] Failed to load libraries:', error)
      throw new Error(`Failed to load Live2D libraries: ${error}`)
    }
  }

  private async init(): Promise<void> {
    await this.loadLibraries()

    if (!this.app) {
      try {
        // 获取容器的实际尺寸
        const containerWidth = this.canvas.clientWidth || 800
        const containerHeight = this.canvas.clientHeight || 600

        // 创建 PIXI 应用
        this.app = new this.PIXI.Application({
          view: this.canvas,
          width: containerWidth,
          height: containerHeight,
          backgroundAlpha: 0,
          autoDensity: true,
          resolution: window.devicePixelRatio || 1,
        })

        logger.info('[Live2DService] PIXI 应用已初始化')
      } catch (error) {
        logger.error('[Live2DService] 初始化失败:', error)
        throw error
      }
    }
  }

  async loadModel(): Promise<void> {
    await this.init()

    if (!this.app) {
      throw new Error('[Live2DService] PIXI 应用未初始化')
    }

    try {
      logger.info(`[Live2DService] 正在加载模型: ${this.config.path}`)

      // 加载 Live2D 模型
      this.model = await this.Live2DModel.from(this.config.path)

      // 调试：打印模型初始尺寸
      logger.info('[Live2DService] 模型加载成功，原始尺寸:', {
        width: this.model.width,
        height: this.model.height,
        x: this.model.x,
        y: this.model.y,
        scale: this.model.scale.x,
      })

      // 设置缩放和位置
      if (this.config.scale) {
        this.model.scale.set(this.config.scale)
      }

      if (this.config.position) {
        this.model.position.set(this.config.position.x, this.config.position.y)
      }

      // 调试：打印设置后的尺寸
      logger.info('[Live2DService] 模型设置后:', {
        x: this.model.x,
        y: this.model.y,
        scale: this.model.scale.x,
        width: this.model.width,
        height: this.model.height,
      })

      // 添加到舞台
      this.app.stage.addChild(this.model)

      logger.info('[Live2DService] 模型已添加到舞台')
      this.emit('model:loaded')
    } catch (error) {
      logger.error('[Live2DService] 模型加载失败:', error)
      this.emit('model:error', error)
      throw error
    }
  }

  /**
   * 设置情感到 motion index 的映射
   * 应该在加载模型后调用
   */
  setEmotionMap(map: Record<string, number>): void {
    this.emotionMap = { ...map }
    logger.info('[Live2DService] 情感映射已设置:', this.emotionMap)
  }

  /**
   * 设置表情（基于情感内容）
   * @param emotion 情感名称 (happy, sad, angry, 等)
   */
  setExpression(emotion: string): void {
    if (!this.model) {
      logger.warn('[Live2DService] 模型未加载，无法设置表情')
      return
    }

    logger.debug(`[Live2DService] 设置表情: ${emotion}`)

    try {
      // 获取对应的 motion index
      const motionIndex = this.emotionMap[emotion] ?? 0

      // 播放动作（使用 idle 动作组）
      this.model.motion('idle', motionIndex)

      this.currentExpression = emotion
      this.emit('expression:change', emotion)
    } catch (error) {
      logger.error(`[Live2DService] 设置表情失败: ${emotion}`, error)
    }
  }

  /**
   * 播放表情时间轴
   * @param segments 时间轴片段数组
   * @param totalDuration 总时长（秒）
   */
  playTimeline(segments: TimelineSegment[], totalDuration: number): ExpressionTimeline {
    // 停止当前时间轴
    if (this.currentTimeline) {
      this.currentTimeline.stop()
    }

    // 创建新的时间轴
    this.currentTimeline = new ExpressionTimeline(
      segments,
      totalDuration,
      (emotion) => this.setExpression(emotion)
    )

    // 开始播放
    this.currentTimeline.play()

    logger.info(
      `[Live2DService] 开始播放表情时间轴: ${segments.length} 个片段, ` +
      `总时长 ${totalDuration}s`
    )

    return this.currentTimeline
  }

  /**
   * 停止当前时间轴
   */
  stopTimeline(): void {
    if (this.currentTimeline) {
      this.currentTimeline.stop()
      this.currentTimeline = null
      logger.debug('[Live2DService] 时间轴已停止')
    }
  }

  /**
   * 重置到默认表情
   */
  resetExpression(): void {
    this.stopTimeline()
    this.setExpression('neutral')
  }

  setMouthOpen(value: number): void {
    if (!this.model) return

    try {
      // 设置嘴部张开程度 (0-1)
      // 注意：具体的参数名称取决于 Live2D 模型
      const internalModel = this.model.internalModel

      // 尝试设置嘴部参数（需要根据具体模型调整）
      if (internalModel && typeof value === 'number') {
        // 这里是一个简化实现，实际需要根据模型的具体参数来调整
        // internalModel.coreModel.setParameterValueById('ParamMouthOpenUp', value)
      }
    } catch (error) {
      logger.debug('[Live2DService] 设置嘴部动作失败（可能是模型不支持）:', error)
    }
  }

  destroy(): void {
    if (this.model) {
      this.app?.stage.removeChild(this.model)
      this.model.destroy()
      this.model = null
    }

    if (this.app) {
      try {
        // 安全销毁，处理可能的 resize plugin 错误
        if (typeof this.app.destroy === 'function') {
          this.app.destroy(true, { children: true, texture: true })
        }
      } catch (error) {
        logger.warn('[Live2DService] 销毁 PIXI 应用时出错（已忽略）:', error)
      }
      this.app = null
    }

    this.removeAllListeners()
    logger.info('[Live2DService] 已销毁')
  }

  isModelLoaded(): boolean {
    return this.model !== null
  }

  getCurrentExpression(): string {
    return this.currentExpression
  }
}
