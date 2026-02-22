/**
 * Live2D 类型定义
 */

export interface Live2DExpression {
  name: string
  opacity?: number
  duration?: number
}

export interface Live2DModelConfig {
  path: string
  scale?: number
  position?: {
    x: number
    y: number
  }
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
  lipSync: {
    enabled: boolean
    sensitivity: number
    smoothing: number
  }
}
