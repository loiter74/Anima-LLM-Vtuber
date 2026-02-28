/**
 * Live2D 位置配置
 * 用于配置 Live2D 模型在容器中的显示位置
 */

export interface Live2DPositionConfig {
  /** Y 轴偏移百分比（0-100），正值向下偏移 */
  yOffsetPercent: number
  /** X 轴偏移百分比（0-100），正值向右偏移 */
  xOffsetPercent: number
  /** 缩放倍数 */
  scaleMultiplier: number
}

/**
 * VTuber 头像默认位置配置
 * 使用居中配置以避免定位问题
 */
export const DEFAULT_VTUBER_POSITION: Live2DPositionConfig = {
  yOffsetPercent: 0,   // 居中（修复：之前 50 导致模型在画布下方）
  xOffsetPercent: 0,   // X 轴居中
  scaleMultiplier: 1.0 // 不放大（避免超出画布）
}

/**
 * 完全居中配置
 */
export const CENTERED_POSITION: Live2DPositionConfig = {
  yOffsetPercent: 0,
  xOffsetPercent: 0,
  scaleMultiplier: 1.0
}

/**
 * 头像风格配置（更靠上）
 */
export const PORTRAIT_POSITION: Live2DPositionConfig = {
  yOffsetPercent: 10,
  xOffsetPercent: 0,
  scaleMultiplier: 1.0
}

/**
 * 半身风格配置（更靠下）
 */
export const HALF_BODY_POSITION: Live2DPositionConfig = {
  yOffsetPercent: 30,
  xOffsetPercent: 0,
  scaleMultiplier: 1.0
}
