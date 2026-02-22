/**
 * Live2D 服务
 * 管理 Live2D 模型的加载、渲染和表情控制
 */

import { EventEmitter } from 'events'
import { Application } from 'pixi.js'
import { Live2DModel } from 'pixi-live2d-display'
import { logger } from '@/shared/utils/logger'
import type { Live2DExpression, Live2DModelConfig } from '../types'

export class Live2DService extends EventEmitter {
  private app: Application | null = null
  private model: Live2DModel | null = null
  private currentExpression: string = 'idle'
  private canvas: HTMLCanvasElement
  private config: Live2DModelConfig

  constructor(canvas: HTMLCanvasElement, config: Live2DModelConfig) {
    super()
    this.canvas = canvas
    this.config = config

    this.init()
  }

  private init(): void {
    try {
      // 创建 PIXI 应用
      this.app = new Application({
        view: this.canvas,
        backgroundAlpha: 0,
        resizeTo: window,
        autoDensity: true,
        resolution: window.devicePixelRatio || 1,
      })

      logger.info('[Live2DService] PIXI 应用已初始化')
    } catch (error) {
      logger.error('[Live2DService] 初始化失败:', error)
      throw error
    }
  }

  async loadModel(): Promise<void> {
    if (!this.app) {
      throw new Error('[Live2DService] PIXI 应用未初始化')
    }

    try {
      logger.info(`[Live2DService] 正在加载模型: ${this.config.path}`)

      // 加载 Live2D 模型
      this.model = await Live2DModel.from(this.config.path)

      // 设置缩放和位置
      if (this.config.scale) {
        this.model.scale.set(this.config.scale)
      }

      if (this.config.position) {
        this.model.position.set(this.config.position.x, this.config.position.y)
      }

      // 添加到舞台
      // @ts-ignore - pixi-live2d-display types are not perfectly compatible with pixi.js v8
      this.app.stage.addChild(this.model)

      logger.info('[Live2DService] 模型加载成功')
      this.emit('model:loaded')
    } catch (error) {
      logger.error('[Live2DService] 模型加载失败:', error)
      this.emit('model:error', error)
      throw error
    }
  }

  setExpression(expression: string): void {
    if (!this.model) {
      logger.warn('[Live2DService] 模型未加载，无法设置表情')
      return
    }

    logger.debug(`[Live2DService] 设置表情: ${expression}`)

    // 表情到动作组的映射
    const motionMap: Record<string, string> = {
      idle: 'idle',
      listening: 'listening',
      thinking: 'thinking',
      speaking: 'speaking',
      surprised: 'surprised',
      sad: 'sad',
    }

    const motion = motionMap[expression] || 'idle'

    try {
      // 播放动作
      this.model.motion(motion, 0)

      this.currentExpression = expression
      this.emit('expression:change', expression)
    } catch (error) {
      logger.error(`[Live2DService] 设置表情失败: ${expression}`, error)
    }
  }

  setMouthOpen(value: number): void {
    if (!this.model) return

    try {
      // 设置嘴部张开程度 (0-1)
      // 注意：具体的参数名称取决于 Live2D 模型
      // 常见的嘴部参数名: ParamMouthOpenUp, ParamMouthOpenDown
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
      // @ts-ignore - pixi-live2d-display types are not perfectly compatible with pixi.js v8
      this.app?.stage.removeChild(this.model)
      this.model.destroy()
      this.model = null
    }

    if (this.app) {
      this.app.destroy(true)
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
