/**
 * Live2D 唇同步引擎
 * 使用 Web Audio API 分析音频并驱动嘴部动作
 *
 * Note: This file uses browser-only APIs (AudioContext, window)
 * It must only be imported from client components with "use client" directive
 */

import { logger } from '@/shared/utils/logger'

export interface LipSyncConfig {
  /** 更新频率限制（毫秒），默认 33ms (~30fps） */
  updateInterval?: number
  /** 是否启用平滑处理，默认 true */
  enableSmoothing?: boolean
  /** 平滑系数 (0.0 - 1.0)，默认 0.5 */
  smoothingFactor?: number
  /** 音量乘数，默认 1.0 */
  volumeMultiplier?: number
}

export class LipSyncEngine {
  private audioContext: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private dataArray: Uint8Array | null = null
  private source: MediaElementAudioSourceNode | null = null
  private animationId: number | null = null
  private onUpdate: (value: number) => void
  private config: LipSyncConfig

  // 基于预计算音量的播放
  private volumesAnimationId: number | null = null
  private volumes: number[] = []
  private volumesStartTime: number = 0
  private volumesSampleRate: number = 50 // Hz
  private lastUpdateTime: number = 0
  private smoothedValue: number = 0

  constructor(onUpdate: (value: number) => void, config: LipSyncConfig = {}) {
    this.onUpdate = onUpdate
    this.config = {
      updateInterval: config.updateInterval ?? 33,
      enableSmoothing: config.enableSmoothing ?? true,
      smoothingFactor: config.smoothingFactor ?? 0.5,
      volumeMultiplier: config.volumeMultiplier ?? 1.0,
    }
  }

  async connect(audioElement: HTMLAudioElement): Promise<void> {
    try {
      // Check for SSR
      if (typeof window === 'undefined') {
        logger.warn('[LipSyncEngine] Running in SSR mode, cannot connect audio')
        return
      }

      // 创建 AudioContext
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()

      // 创建分析器
      this.analyser = this.audioContext.createAnalyser()
      this.analyser.fftSize = 512
      this.analyser.smoothingTimeConstant = 0.5

      const bufferLength = this.analyser.frequencyBinCount
      this.dataArray = new Uint8Array(bufferLength)

      // 创建音频源
      this.source = this.audioContext.createMediaElementSource(audioElement)
      this.source.connect(this.analyser)
      this.analyser.connect(this.audioContext.destination)

      logger.info('[LipSyncEngine] 已连接音频元素')
      this.startAnalysis()
    } catch (error) {
      logger.error('[LipSyncEngine] 连接失败:', error)
      throw error
    }
  }

  /**
   * 基于预计算的音量包络开始播放
   * @param volumes 音量包络数组 [0.0, 1.0]
   * @param sampleRate 采样率（Hz）
   */
  startWithVolumes(volumes: number[], sampleRate: number = 50): void {
    this.volumes = volumes
    this.volumesSampleRate = sampleRate
    this.volumesStartTime = performance.now()

    logger.debug(
      `[LipSyncEngine] 开始预计算音量播放: ${volumes.length} 采样点, ` +
      `${sampleRate} Hz`
    )

    this.startVolumesAnimation()
  }

  /**
   * 预计算音量的动画循环
   */
  private startVolumesAnimation(): void {
    const animate = () => {
      const currentTime = performance.now()
      const elapsed = (currentTime - this.volumesStartTime) / 1000 // 秒

      // 计算当前应该播放的采样点索引
      const sampleIndex = Math.floor(elapsed * this.volumesSampleRate)

      if (sampleIndex >= this.volumes.length) {
        // 播放完成
        this.onUpdate(0)
        this.volumesAnimationId = null
        this.smoothedValue = 0
        logger.debug('[LipSyncEngine] 预计算音量播放完成')
        return
      }

      // 获取当前音量
      let volume = this.volumes[sampleIndex]

      // 应用音量乘数
      volume = volume * this.config.volumeMultiplier

      // 应用平滑处理
      if (this.config.enableSmoothing) {
        this.smoothedValue = this.smoothedValue * this.config.smoothingFactor + volume * (1 - this.config.smoothingFactor)
        volume = this.smoothedValue
      } else {
        this.smoothedValue = volume
      }

      // 确保值在 [0, 1] 范围内
      volume = Math.max(0, Math.min(1, volume))

      this.onUpdate(volume)

      // 继续动画
      this.volumesAnimationId = requestAnimationFrame(animate)
    }

    this.volumesAnimationId = requestAnimationFrame(animate)
  }

  /**
   * 停止预计算音量的播放
   */
  stopVolumes(): void {
    if (this.volumesAnimationId !== null) {
      cancelAnimationFrame(this.volumesAnimationId)
      this.volumesAnimationId = null
      this.onUpdate(0)
      this.smoothedValue = 0
      logger.debug('[LipSyncEngine] 停止预计算音量播放')
    }
  }

  private startAnalysis(): void {
    if (!this.analyser || !this.dataArray) return

    const analyze = () => {
      if (!this.analyser || !this.dataArray) return

      this.analyser.getByteFrequencyData(this.dataArray)

      // 计算平均音量
      const sum = this.dataArray.reduce((a, b) => a + b, 0)
      const average = sum / this.dataArray.length
      const normalized = average / 255

      this.onUpdate(normalized)
      this.animationId = requestAnimationFrame(analyze)
    }

    analyze()
  }

  disconnect(): void {
    if (this.animationId !== null) {
      cancelAnimationFrame(this.animationId)
      this.animationId = null
    }

    this.stopVolumes()

    if (this.source) {
      this.source.disconnect()
      this.source = null
    }

    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }

    this.smoothedValue = 0
    logger.info('[LipSyncEngine] 已断开连接')
  }
}
