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
 * 头部显示在画面中上部，身体在下方
 */
export const DEFAULT_VTUBER_POSITION: Live2DPositionConfig = {
  yOffsetPercent: 40,  // 向下偏移 40%，让头部在上方
  xOffsetPercent: 0,   // X 轴居中
  scaleMultiplier: 1.1  // 放大 10%
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
