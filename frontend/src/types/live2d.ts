export interface Live2DConfig {
  modelUrl: string
  scale: number
  x: number
  y: number
}

export type ExpressionType = string

export type Live2DAction =
  | { type: 'expression'; name: string }
  | { type: 'motion'; group: string; index: number }
  | { type: 'param'; name: string; value: number }
  | { type: 'sequence'; actions: Live2DAction[] }
  | { type: 'wait'; ms: number }

export interface AudioWithExpression {
  audio_path: string
  text: string
  emotions: string[]
  volumes: number[]
}
