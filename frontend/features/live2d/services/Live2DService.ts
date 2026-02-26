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
  private isDestroying: boolean = false
  private destroyPromise: Promise<void> | null = null

  // 唇同步相关
  private mouthParamIndex: number = -1
  private formParamIndex: number = -1
  private currentMouthValue: number = 0
  private lastMouthUpdateTime: number = 0

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

  /**
   * 设置窗口大小调整监听器
   */
  private setupResizeListener(): void {
    if (typeof window === 'undefined') return

    let resizeTimeout: number | null = null

    window.addEventListener('resize', () => {
      // 防抖处理
      if (resizeTimeout) {
        clearTimeout(resizeTimeout)
      }

      resizeTimeout = window.setTimeout(() => {
        this.handleResize()
      }, 100)
    })
  }

  /**
   * 处理窗口大小变化
   */
  private handleResize(): void {
    if (!this.app || !this.canvas) return

    try {
      const containerWidth = this.canvas.clientWidth || 800
      const containerHeight = this.canvas.clientHeight || 600

      // 更新 renderer 尺寸
      this.app.renderer.resize(containerWidth, containerHeight)

      logger.debug('[Live2DService] 画布尺寸已调整:', {
        width: containerWidth,
        height: containerHeight,
      })
    } catch (error) {
      logger.warn('[Live2DService] 调整画布尺寸时出错:', error)
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
          resizeTo: this.canvas, // 自动调整大小到 canvas 元素
        })

        // 设置窗口大小调整监听器
        this.setupResizeListener()

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
    if (!this.model || !this.config.lipSync?.enabled) return

    try {
      const internalModel = this.model.internalModel
      if (!internalModel) return

      const coreModel = internalModel.coreModel
      if (!coreModel) return

      // 性能优化：限制更新频率为 ~30fps
      const now = performance.now()
      if (now - this.lastMouthUpdateTime < 33) {
        return
      }
      this.lastMouthUpdateTime = now

      // 确保值在 [0, 1] 范围内
      const clampedValue = Math.max(0, Math.min(1, value))

      // 应用阈值过滤（避免噪音触发嘴部动作）
      const threshold = this.config.lipSync?.minThreshold ?? 0.05
      const filteredValue = clampedValue > threshold ? clampedValue : 0

      // 应用灵敏度调整
      const sensitivity = this.config.lipSync?.sensitivity ?? 1.0
      const scaledValue = Math.min(1, filteredValue * sensitivity)

      // 平滑处理（避免突变）
      const smoothing = this.config.lipSync?.smoothing ?? 0.3
      const smoothedValue = this.currentMouthValue * smoothing + scaledValue * (1 - smoothing)
      this.currentMouthValue = smoothedValue

      // 懒加载并缓存参数索引
      if (this.mouthParamIndex < 0) {
        this.mouthParamIndex = coreModel.getParameterIndex('ParamMouthOpenY')
      }

      if (this.mouthParamIndex >= 0) {
        // 应用最大值限制
        const maxValue = this.config.lipSync?.maxValue ?? 1.0
        const finalValue = Math.min(maxValue, smoothedValue)

        coreModel.setParameterValueByIndex(this.mouthParamIndex, finalValue)
      }

      // 可选：同时控制嘴形（如果配置启用）
      if (this.config.lipSync?.useMouthForm) {
        if (this.formParamIndex < 0) {
          this.formParamIndex = coreModel.getParameterIndex('ParamMouthForm')
        }

        if (this.formParamIndex >= 0) {
          // 嘴形变化幅度较小（30%）
          coreModel.setParameterValueByIndex(
            this.formParamIndex,
            smoothedValue * 0.3
          )
        }
      }
    } catch (error) {
      // 只在开发模式下输出详细错误
      if (process.env.NODE_ENV === 'development') {
        logger.debug('[Live2DService] 设置嘴部动作失败:', error)
      }
    }
  }

  /**
   * 销毁 Live2D 服务
   * 返回 Promise，确保 WebGL 上下文完全释放
   */
  async destroy(): Promise<void> {
    // 防止重复销毁
    if (this.isDestroying) {
      return this.destroyPromise
    }

    this.isDestroying = true

    // 停止时间轴
    this.stopTimeline()

    // 移除所有事件监听器
    this.removeAllListeners()

    // 销毁模型
    if (this.model) {
      try {
        this.app?.stage.removeChild(this.model)
        this.model.destroy()
      } catch (error) {
        logger.warn('[Live2DService] 销毁模型时出错（已忽略）:', error)
      }
      this.model = null
    }

    // 销毁 PIXI 应用
    if (this.app) {
      try {
        // 停止 Ticker 防止继续渲染
        if (this.app.ticker) {
          this.app.ticker.stop()
        }

        // 销毁应用（app.destroy 会自动销毁 renderer）
        if (typeof this.app.destroy === 'function') {
          this.app.destroy(true, { children: true, texture: true, baseTexture: true })
        }
      } catch (error) {
        logger.warn('[Live2DService] 销毁 PIXI 应用时出错（已忽略）:', error)
      }
      this.app = null
    }

    // 等待 WebGL 上下文完全释放
    this.destroyPromise = new Promise(resolve => {
      setTimeout(() => {
        this.isDestroying = false
        this.destroyPromise = null
        logger.info('[Live2DService] 已销毁')
        resolve()
      }, 150) // 增加到 150ms 确保 WebGL 上下文完全释放
    })

    return this.destroyPromise
  }

  isModelLoaded(): boolean {
    return this.model !== null
  }

  getCurrentExpression(): string {
    return this.currentExpression
  }
}
