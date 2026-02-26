/**
 * Socket.IO Event Type Definitions
 * 后端到前端的事件类型定义
 */

import { EventType } from '@/features/connection/constants/events'

/**
 * 基础事件接口
 */
export interface BaseEvent {
  type: string
  seq?: number
  metadata?: Record<string, unknown>
}

/**
 * 文本事件
 */
export interface TextEvent extends BaseEvent {
  type: typeof EventType.TEXT
  text: string
  is_complete?: boolean
}

/**
 * 音频事件
 */
export interface AudioEvent extends BaseEvent {
  type: typeof EventType.AUDIO
  audio_path?: string
  audio_data?: string
  format?: string
}

/**
 * 转录事件（ASR 结果）
 */
export interface TranscriptEvent extends BaseEvent {
  type: typeof EventType.TRANSCRIPT
  text: string
}

/**
 * 控制事件
 */
export interface ControlEvent extends BaseEvent {
  type: typeof EventType.CONTROL
  text: string
}

/**
 * 错误事件
 */
export interface ErrorEvent extends BaseEvent {
  type: typeof EventType.ERROR
  message: string
}

/**
 * 表情事件（旧版，基于状态）
 */
export interface ExpressionEvent extends BaseEvent {
  type: 'expression'
  expression: string
  timestamp?: number
}

/**
 * 时间轴片段
 */
export interface ExpressionSegment {
  emotion: string
  time: number      // 开始时间（秒）
  duration: number  // 持续时间（秒）
}

/**
 * 表情时间轴数据
 */
export interface ExpressionTimeline {
  segments: ExpressionSegment[]
  total_duration: number
}

/**
 * 音频 + 表情统一事件（新版，基于情感内容）
 */
export interface AudioWithExpressionEvent extends BaseEvent {
  type: 'audio_with_expression'
  audio_data: string          // base64 编码的音频数据
  format: string              // 音频格式 (mp3, wav, 等)
  volumes: number[]           // 音量包络数组 [0.0, 1.0]
  expressions: ExpressionTimeline  // 表情时间轴
  text: string                // 清理后的文本
}

/**
 * 所有事件类型的联合
 */
export type ServerEvent =
  | TextEvent
  | AudioEvent
  | TranscriptEvent
  | ControlEvent
  | ErrorEvent
  | ExpressionEvent
  | AudioWithExpressionEvent

/**
 * 事件类型守卫
 */
export function isAudioWithExpressionEvent(
  event: BaseEvent
): event is AudioWithExpressionEvent {
  return event.type === 'audio_with_expression'
}

export function isTextEvent(event: BaseEvent): event is TextEvent {
  return event.type === EventType.TEXT
}

export function isAudioEvent(event: BaseEvent): event is AudioEvent {
  return event.type === EventType.AUDIO
}

export function isTranscriptEvent(event: BaseEvent): event is TranscriptEvent {
  return event.type === EventType.TRANSCRIPT
}

export function isControlEvent(event: BaseEvent): event is ControlEvent {
  return event.type === EventType.CONTROL
}

export function isErrorEvent(event: BaseEvent): event is ErrorEvent {
  return event.type === EventType.ERROR
}

export function isExpressionEvent(event: BaseEvent): event is ExpressionEvent {
  return event.type === 'expression'
}
