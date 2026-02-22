/**
 * Live2D 唇同步引擎
 * 使用 Web Audio API 分析音频并驱动嘴部动作
 */

import { logger } from '@/shared/utils/logger'

export class LipSyncEngine {
  private audioContext: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private dataArray: Uint8Array | null = null
  private source: MediaElementAudioSourceNode | null = null
  private animationId: number | null = null
  private onUpdate: (value: number) => void

  constructor(onUpdate: (value: number) => void) {
    this.onUpdate = onUpdate
  }

  async connect(audioElement: HTMLAudioElement): Promise<void> {
    try {
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

    if (this.source) {
      this.source.disconnect()
      this.source = null
    }

    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }

    logger.info('[LipSyncEngine] 已断开连接')
  }
}
