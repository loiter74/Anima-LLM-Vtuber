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
import { DEFAULT_VTUBER_POSITION, type Live2DPositionConfig } from '../config'

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
  private resizeObserver: ResizeObserver | null = null
  private positionConfig: Live2DPositionConfig = DEFAULT_VTUBER_POSITION

  // 唇同步相关
  private mouthParamIndex: number = -1
  private formParamIndex: number = -1
  private currentMouthValue: number = 0
  private lastMouthUpdateTime: number = 0
  private callCount: number = 0  // 用于日志记录
  private lastLogTime: number = 0  // 用于日志记录

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

    // 监听窗口大小变化
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

    // 使用 ResizeObserver 监听 canvas 元素本身的大小变化
    // 这对于响应式布局特别重要（当布局变化时容器大小可能改变）
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const { width, height } = entry.contentRect

          // 防抖处理
          if (resizeTimeout) {
            clearTimeout(resizeTimeout)
          }

          resizeTimeout = window.setTimeout(() => {
            this.handleResize()
          }, 100)
        }
      })

      // 开始观察 canvas 元素
      this.resizeObserver.observe(this.canvas)

      logger.debug('[Live2DService] ResizeObserver 已设置')
    }
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

      // 自动调整模型缩放和位置
      this.autoScaleModel(containerWidth, containerHeight)

      logger.debug('[Live2DService] 画布尺寸已调整:', {
        width: containerWidth,
        height: containerHeight,
      })
    } catch (error) {
      logger.warn('[Live2DService] 调整画布尺寸时出错:', error)
    }
  }

  /**
   * 自动调整模型缩放和位置以适应容器
   * @param containerWidth 容器宽度
   * @param containerHeight 容器高度
   */
  private autoScaleModel(containerWidth: number, containerHeight: number): void {
    if (!this.model) return

    try {
      // 获取模型的原始尺寸
      const internalModel = this.model.internalModel
      const originalWidth = internalModel?.canvasWidth || this.model.width
      const originalHeight = internalModel?.canvasHeight || this.model.height

      // 计算缩放比例（留出 5% 的边距）
      const padding = 0.05
      const targetWidth = containerWidth * (1 - padding)
      const targetHeight = containerHeight * (1 - padding)

      const scaleX = targetWidth / originalWidth
      const scaleY = targetHeight / originalHeight

      // 使用较大的缩放比例让模型填充更多空间
      const autoScale = Math.max(scaleX, scaleY)

      // 应用缩放倍数
      const finalScale = autoScale * this.positionConfig.scaleMultiplier

      // 设置模型缩放
      this.model.scale.set(finalScale)

      // 设置锚点为中心
      this.model.anchor.set(0.5, 0.5)

      // 计算位置（中心 + 配置偏移）
      const centerX = containerWidth / 2
      const centerY = containerHeight / 2

      // 🔧 简化：offsetPercent 是相对于容器尺寸的偏移百分比
      // yOffsetPercent: 0 = 居中
      // yOffsetPercent: 10 = 向下偏移容器高度的 10%
      // yOffsetPercent: -10 = 向上偏移容器高度的 10%
      const yOffset = containerHeight * (this.positionConfig.yOffsetPercent / 100)
      const xOffset = containerWidth * (this.positionConfig.xOffsetPercent / 100)

      this.model.x = centerX + xOffset
      this.model.y = centerY + yOffset

      logger.info('[Live2DService] 模型位置设置:', {
        container: { width: containerWidth, height: containerHeight },
        config: this.positionConfig,
        calculated: {
          center: { x: centerX, y: centerY },
          offset: { x: xOffset, y: yOffset },
          final: { x: this.model.x, y: this.model.y }
        },
        finalScale: finalScale.toFixed(3)
      })
    } catch (error) {
      logger.warn('[Live2DService] 位置设置失败:', error)
    }
  }

  /**
   * 设置位置配置
   * @param config 位置配置
   */
  setPositionConfig(config: Partial<Live2DPositionConfig>): void {
    this.positionConfig = { ...this.positionConfig, ...config }
    logger.info('[Live2DService] 位置配置已更新:', this.positionConfig)

    // 重新应用位置
    const canvasWidth = this.canvas.clientWidth || 800
    const canvasHeight = this.canvas.clientHeight || 600
    this.autoScaleModel(canvasWidth, canvasHeight)
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
        anchor: this.model.anchor,
      })

      // 设置模型的锚点为中心（重要！让缩放和定位从中心开始）
      this.model.anchor.set(0.5, 0.5)

      // 注意：不在这里设置 config.scale 和 config.position
      // 让 autoScaleModel 完全控制缩放和位置

      // 添加到舞台
      this.app.stage.addChild(this.model)

      logger.info('[Live2DService] 模型已添加到舞台')

      // 自动调整模型缩放和位置（会设置正确的 scale 和 position）
      const containerWidth = this.canvas.clientWidth || 800
      const containerHeight = this.canvas.clientHeight || 600
      this.autoScaleModel(containerWidth, containerHeight)

      // 暴露到 window 对象以便调试
      if (typeof window !== 'undefined') {
        (window as any).__live2dService = this

        // 添加辅助方法来检查模型参数
      const internalModel = this.model.internalModel
      if (internalModel?.coreModel) {
        const coreModel = internalModel.coreModel
        const paramCount = coreModel.getParameterCount()

        logger.info(`[Live2DService] ====== 模型参数信息 ======`)
        logger.info(`[Live2DService] 总参数数: ${paramCount}`)

        // 查找所有包含 "Mouth" 的参数
        const mouthParams: string[] = []
        for (let i = 0; i < paramCount; i++) {
          try {
            // 尝试获取参数值
            const value = coreModel.getParameterValueByIndex(i)

            // 列出所有参数及其值
            if (i < 20) {  // 只记录前20个
              logger.info(`[Live2DService] 参数[${i}]: 值=${value.toFixed(3)}`)
            }
          } catch (e) {
            // 忽略错误
          }
        }

        // 手动测试 ParamMouthOpenY
        try {
          const mouthIndex = coreModel.getParameterIndex('ParamMouthOpenY')
          const currentValue = coreModel.getParameterValueByIndex(mouthIndex)
          logger.info(`[Live2DService] ParamMouthOpenY 找到! 索引=${mouthIndex}, 当前值=${currentValue.toFixed(3)}`)

          // 测试设置参数
          coreModel.setParameterValueByIndex(mouthIndex, 1.0)
          const testValue = coreModel.getParameterValueByIndex(mouthIndex)
          logger.info(`[Live2DService] 测试设置为 1.0 后, 值=${testValue.toFixed(3)}`)

          // 恢复原值
          coreModel.setParameterValueByIndex(mouthIndex, currentValue)
        } catch (e) {
          logger.error('[Live2DService] ParamMouthOpenY 测试失败:', e)
        }
      }
      }

      // ✅ 在下一帧发出事件，确保 DOM 更新完成
      requestAnimationFrame(() => {
        this.emit('model:loaded')
      })
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
   * 设置表情（支持强度）
   * @param emotion 表情名称
   * @param intensity 强度值 (0.0 - 1.0)
   */
  setExpression(emotion: string, intensity: number = 1.0): void {
    logger.info(`[Live2DService] ========== setExpression 被调用 ==========`)
    logger.info(`[Live2DService] 表情: ${emotion}, 强度: ${intensity.toFixed(2)}`)

    this.currentExpression = emotion

    // 触发 Live2D 模型的表情动作
    if (this.model) {
      // 从 emotionMap 获取 expression index
      const expressionIndex = this.emotionMap[emotion]

      if (expressionIndex !== undefined) {
        try {
          // Live2D 的 expressions 使用 expression() 方法，不是 motion()
          // expressions 是参数预设，不是动画片段
          this.model.expression(expressionIndex)
          logger.info(`[Live2DService] ✅ 触发表情: ${emotion} (expression index: ${expressionIndex})`)
        } catch (error) {
          logger.warn(`[Live2DService] 触发表情失败: ${error}`)
        }
      } else {
        logger.warn(`[Live2DService] 未找到表情 "${emotion}" 的 expression index`)
        logger.info(`[Live2DService] 当前 emotionMap:`, this.emotionMap)
      }
    } else {
      logger.warn('[Live2DService] 模型未加载，无法设置表情')
    }

    // TODO: 如果 Live2D 模型支持强度参数，在这里应用
    // 例如：model.setParameter('ParamEyeLOpen', intensity)
  }

  /**
   * 清空当前表情，让模型回到 Idle Motion 控制的默认状态
   */
  clearExpression(): void {
    logger.info('[Live2DService] ========== clearExpression 被调用 ==========')
    logger.info('[Live2DService] 清空表情，模型应回到 Idle Motion 状态')

    this.currentExpression = 'neutral'

    if (this.model) {
      try {
        // 尝试不同的方法来清空表情
        // 方法 1: 传入 -1 或 undefined 来清空
        if (typeof this.model.expression === 'function') {
          // pixi-live2d-display 的 expression() 方法接受索引
          // 传入无效值或不传参数可能会清空当前表情
          try {
            (this.model.expression as any)(-1)  // 尝试传入 -1
            logger.info('[Live2DService] ✅ 已尝试清空表情（方法 1: expression(-1)）')
          } catch (e) {
            // 方法 2: 不做任何操作，让 Expression 自然淡出
            logger.info('[Live2DService] 表情会自然淡出，让 Idle Motion 接管')
          }
        }
      } catch (error) {
        logger.warn('[Live2DService] 清空表情时出错（已忽略）:', error)
      }
    }
  }

  /**
   * 播放时间轴（支持强度）
   * @param segments 时间轴片段（包含 intensity）
   * @param totalDuration 总时长
   */
  playTimeline(segments: TimelineSegment[], totalDuration: number): ExpressionTimeline {
    logger.info(
      `[Live2DService] 开始播放时间轴: ${segments.length} 个片段, 总时长 ${totalDuration}s`
    )

    segments.forEach((seg, index) => {
      const { emotion, time, duration, intensity = 1.0 } = seg  // 默认值 1.0

      logger.debug(
        `[Live2DService] 片段 ${index + 1}: ${emotion} ` +
        `(time: ${time.toFixed(2)}s, duration: ${duration.toFixed(2)}s, ` +
        `intensity: ${intensity.toFixed(2)})`
      )
    })

    // 停止当前时间轴
    if (this.currentTimeline) {
      this.currentTimeline.stop()
    }

    // 创建新的时间轴（ExpressionTimeline 会自动处理表情调度）
    this.currentTimeline = new ExpressionTimeline(
      segments,
      totalDuration,
      (emotion, intensity) => this.setExpression(emotion, intensity)
    )

    // 开始播放
    this.currentTimeline.play()

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
   * 重置到默认表情（清空表情，回到 Idle Motion）
   */
  resetExpression(): void {
    this.stopTimeline()
    this.clearExpression()
  }

  setMouthOpen(value: number): void {
    // 静默返回（减少日志噪音）
    if (!this.model || !this.config.lipSync?.enabled) return

    try {
      const internalModel = this.model.internalModel
      if (!internalModel) return

      const coreModel = internalModel.coreModel
      if (!coreModel) return

      // 性能优化：限制更新频率为 ~30fps
      const now = performance.now()
      const updateInterval = 33  // ~30fps
      if (now - this.lastMouthUpdateTime < updateInterval) {
        return
      }
      this.lastMouthUpdateTime = now

      // 🔧 保护：保存当前位置和缩放（防止 update() 改变模型位置）
      const savedX = this.model.x
      const savedY = this.model.y
      const savedScaleX = this.model.scale.x
      const savedScaleY = this.model.scale.y
      const savedAnchorX = this.model.anchor.x
      const savedAnchorY = this.model.anchor.y

      // 首次调用时记录日志
      if (!(this as any).hasLoggedFirstCall) {
        logger.info('[Live2DService] ========== setMouthOpen 首次调用 ==========')
        logger.info(`[Live2DService] 输入值: ${value.toFixed(3)}`)
        logger.info(`[Live2DService] lipSync 配置:`, this.config.lipSync)
        logger.info('[Live2DService] 当前模型位置:', { x: savedX, y: savedY, scale: { x: savedScaleX, y: savedScaleY } })
        ;(this as any).hasLoggedFirstCall = true
      }

      // 确保值在 [0, 1] 范围内
      const clampedValue = Math.max(0, Math.min(1, value))

      // 应用阈值过滤（避免噪音触发嘴部动作）
      const threshold = this.config.lipSync?.minThreshold ?? 0.02
      const filteredValue = clampedValue > threshold ? clampedValue : 0

      // 应用灵敏度调整
      const sensitivity = this.config.lipSync?.sensitivity ?? 2.0
      const scaledValue = Math.min(1, filteredValue * sensitivity)

      // 平滑处理（避免突变）
      const smoothing = this.config.lipSync?.smoothing ?? 0.3
      const smoothedValue = this.currentMouthValue * smoothing + scaledValue * (1 - smoothing)
      this.currentMouthValue = smoothedValue

      // 懒加载并缓存参数索引
      if (this.mouthParamIndex < 0) {
        this.mouthParamIndex = coreModel.getParameterIndex('ParamMouthOpenY')
        logger.info(`[Live2DService] ParamMouthOpenY 索引: ${this.mouthParamIndex}`)
      }

      if (this.mouthParamIndex >= 0) {
        // 应用最大值限制
        const maxValue = this.config.lipSync?.maxValue ?? 1.0
        const finalValue = Math.min(maxValue, smoothedValue)

        // 设置参数值
        coreModel.setParameterValueByIndex(this.mouthParamIndex, finalValue)

        // 🔥 关键：只更新核心模型（cubism4 必需）
        coreModel.update()

        // 🔧 保护：恢复位置和缩放（防止 update() 改变模型位置）
        if (this.model.x !== savedX || this.model.y !== savedY) {
          logger.warn('[Live2DService] 检测到位置变化，恢复原始位置')
          this.model.x = savedX
          this.model.y = savedY
        }
        if (this.model.scale.x !== savedScaleX || this.model.scale.y !== savedScaleY) {
          logger.warn('[Live2DService] 检测到缩放变化，恢复原始缩放')
          this.model.scale.set(savedScaleX, savedScaleY)
        }
        if (this.model.anchor.x !== savedAnchorX || this.model.anchor.y !== savedAnchorY) {
          logger.warn('[Live2DService] 检测到锚点变化，恢复原始锚点')
          this.model.anchor.set(savedAnchorX, savedAnchorY)
        }

        // 同时控制 ParamMouthForm（嘴形参数）以增强视觉效果
        if (this.config.lipSync?.useMouthForm) {
          try {
            if (this.formParamIndex < 0) {
              this.formParamIndex = coreModel.getParameterIndex('ParamMouthForm')
              logger.info(`[Live2DService] ParamMouthForm 索引: ${this.formParamIndex}`)
            }

            if (this.formParamIndex >= 0) {
              // 嘴形参数使用相同的值，但幅度较小（40%）
              coreModel.setParameterValueByIndex(this.formParamIndex, finalValue * 0.4)
              coreModel.update()

              // 🔧 再次保护：确保位置没有被改变
              if (this.model.x !== savedX || this.model.y !== savedY) {
                this.model.x = savedX
                this.model.y = savedY
              }
            }
          } catch (e) {
            // 忽略 ParamMouthForm 错误
          }
        }

        // 记录日志（前10次调用，每秒一次）
        if (!(this as any).callCount) {
          (this as any).callCount = 0
        }
        (this as any).callCount++

        if ((this as any).callCount <= 10 || now - ((this as any).lastLogTime || 0) > 1000) {
          logger.info(
            `[Live2DService] 嘴部参数更新 [${(this as any).callCount}]: ` +
            `索引=${this.mouthParamIndex}, 值=${finalValue.toFixed(3)}, ` +
            `原始值=${value.toFixed(3)}, ` +
            `嘴形=${this.formParamIndex >= 0 ? (finalValue * 0.4).toFixed(3) : 'N/A'}`
          )
          ;(this as any).lastLogTime = now
        }
      } else {
        logger.warn('[Live2DService] ParamMouthOpenY 参数未找到！')
      }
    } catch (error) {
      logger.error('[Live2DService] 设置嘴部动作失败:', error)
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

    // 清理 ResizeObserver
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
      this.resizeObserver = null
      logger.debug('[Live2DService] ResizeObserver 已清理')
    }

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
