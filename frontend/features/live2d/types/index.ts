/**
 * Live2D 类型定义
 */

export interface Live2DExpression {
  name: string
  opacity?: number
  duration?: number
}

/**
 * 唇同步配置
 */
export interface LipSyncConfig {
  /** 是否启用唇同步 */
  enabled: boolean
  /** 嘴部动作灵敏度 (0.5 - 2.0)，默认 1.0 */
  sensitivity?: number
  /** 平滑系数 (0.0 - 1.0)，默认 0.3，避免抖动 */
  smoothing?: number
  /** 最小音量阈值 (0.0 - 1.0)，默认 0.05，低于此值嘴部闭合 */
  minThreshold?: number
  /** 最大嘴部张开度 (0.0 - 1.0)，默认 1.0 */
  maxValue?: number
  /** 是否同时控制嘴形参数，默认 false */
  useMouthForm?: boolean
}

export interface Live2DModelConfig {
  path: string
  scale?: number
  position?: {
    x: number
    y: number
  }
  /** 唇同步配置 */
  lipSync?: LipSyncConfig
}

export interface Live2DExpressionsConfig {
  idle: string
  listening: string
  thinking: string
  speaking: string
  surprised: string
  sad: string
}

export interface Live2DConfig {
  enabled: boolean
  model: Live2DModelConfig
  expressions: Live2DExpressionsConfig
  lipSync: LipSyncConfig
}
