/**
 * Live2D Expression Constants
 * Live2D 表情配置
 */

export interface Expression {
  name: string
  label: string
}

/**
 * Available expressions
 */
export const EXPRESSIONS: Expression[] = [
  { name: "Neutral", label: "Neutral" },
  { name: "Happy", label: "Happy" },
  { name: "Surprised", label: "Surprised" },
  { name: "Thinking", label: "Thinking" },
]
