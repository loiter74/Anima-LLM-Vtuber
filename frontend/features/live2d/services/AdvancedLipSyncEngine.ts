/**
 * 高级 Live2D 唇同步引擎
 * 使用非线性映射、自适应阈值和预测性平滑
 *
 * 核心技术：
 * 1. 时间补偿 (Time Compensation): 音频到嘴部动作的延迟补偿
 * 2. 非线性音量映射 (Non-linear Volume Mapping): 对数曲线代替线性乘法
 * 3. 自适应阈值 (Adaptive Threshold): 动态调整静音阈值
 * 4. 预测性平滑 (Predictive Smoothing): 简单卡尔曼滤波
 */

import { logger } from '@/shared/utils/logger'

export interface AdvancedLipSyncConfig {
  /** 更新频率限制（毫秒），默认 33ms (~30fps) */
  updateInterval?: number
  /** 是否启用平滑处理，默认 true */
  enableSmoothing?: boolean
  /** 平滑系数 (0.0 - 1.0)，默认 0.3，越小平滑越少 */
  smoothingFactor?: number
  /** 基础音量乘数，默认 2.0 */
  baseVolumeMultiplier?: number
  /** 最小音量阈值 (0.0 - 1.0)，默认 0.02 */
  minThreshold?: number
  /** 时间补偿（帧数），默认 2 帧 (~66ms @ 30fps） */
  timeCompensationFrames?: number
  /** 非线性曲线强度 (0.0-1.0)，0=线性，1=完全非线性，默认 0.6 */
  curveIntensity?: number
  /** 自适应阈值启用，默认 true */
  enableAdaptiveThreshold?: boolean
  /** 自适应阈值窗口大小（采样点数），默认 50 */
  adaptiveWindow?: number
  /** 语音检测窗口大小（帧数），默认 15 帧 (~500ms @ 30fps) */
  speechDetectionWindow?: number
  /** 语音检测阈值，超过此值认为在说话，默认 0.03 */
  speechThreshold?: number
  /** 停顿检测窗口大小（帧数），默认 30 帧 (~1秒 @ 30fps) */
  pauseDetectionWindow?: number
  /** 停顿时嘴巴闭合速度 (0.0-1.0)，默认 0.1，越大闭合越快 */
  pauseCloseSpeed?: number
}

export class AdvancedLipSyncEngine {
  private audioContext: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private dataArray: Uint8Array | null = null
  private source: MediaElementAudioSourceNode | null = null
  private animationId: number | null = null
  private onUpdate: (value: number) => void
  private config: AdvancedLipSyncConfig

  // 基于预计算音量的播放
  private volumesAnimationId: number | null = null
  private volumes: number[] = []
  private volumesStartTime: number = 0
  private volumesSampleRate: number = 50 // Hz
  private lastUpdateTime: number = 0

  // 卡尔曼滤波状态
  private kalmanState: {
    x: number      // 估计值
    p: number      // 估计误差
    q: number      // 过程噪声
    r: number      // 测量噪声
  }

  // 自适应阈值状态
  private adaptiveThreshold: {
    current: number
    window: number[]
    history: number[]
  }

  // 语音状态检测
  private speechState: {
    isSpeaking: boolean
    isPaused: boolean
    speechWindow: number[]
    pauseWindow: number[]
    mouthValueDuringPause: number
  }

  constructor(onUpdate: (value: number) => void, config: AdvancedLipSyncConfig = {}) {
    this.onUpdate = onUpdate
    this.config = {
      updateInterval: config.updateInterval ?? 33,
      enableSmoothing: config.enableSmoothing ?? true,
      smoothingFactor: config.smoothingFactor ?? 0.3,
      baseVolumeMultiplier: config.baseVolumeMultiplier ?? 2.0,
      minThreshold: config.minThreshold ?? 0.02,
      timeCompensationFrames: config.timeCompensationFrames ?? 2,
      curveIntensity: config.curveIntensity ?? 0.6,
      enableAdaptiveThreshold: config.enableAdaptiveThreshold ?? true,
      adaptiveWindow: config.adaptiveWindow ?? 50,
      speechDetectionWindow: config.speechDetectionWindow ?? 15,
      speechThreshold: config.speechThreshold ?? 0.03,
      pauseDetectionWindow: config.pauseDetectionWindow ?? 30,
      pauseCloseSpeed: config.pauseCloseSpeed ?? 0.1,
    }

    // 初始化卡尔曼滤波器
    this.kalmanState = {
      x: 0,      // 初始估计值
      p: 1,      // 初始误差
      q: 0.01,   // 过程噪声（较小 = 更平滑）
      r: 0.1,    // 测量噪声（较小 = 更信任测量值）
    }

    // 初始化自适应阈值
    this.adaptiveThreshold = {
      current: this.config.minThreshold,
      window: [],
      history: [],
    }

    // 初始化语音状态
    this.speechState = {
      isSpeaking: false,
      isPaused: false,
      speechWindow: [],
      pauseWindow: [],
      mouthValueDuringPause: 0,
    }
  }

  /**
   * 非线性音量映射 - 对数曲线
   * 让小声音更敏感，大声音不过度放大
   */
  private applyNonLinearCurve(volume: number): number {
    const intensity = this.config.curveIntensity!

    if (intensity === 0) {
      // 线性模式
      return volume
    }

    // 使用对数曲线：small volumes get boosted, large volumes get compressed
    // Formula: output = input^intensity * volumeMultiplier
    const scaled = Math.pow(volume, 1 - intensity * 0.5) // 0.5-1.0 范围
    return scaled
  }

  /**
   * 卡尔曼滤波预测步骤
   */
  private kalmanPredict(): void {
    // 预测：x_k = A * x_{k-1} (这里 A=1)
    this.kalmanState.x = this.kalmanState.x

    // 预测误差：P_k = A * P_{k-1} * A^T + Q
    this.kalmanState.p = this.kalmanState.p + this.kalmanState.q
  }

  /**
   * 卡尔曼滤波更新步骤
   */
  private kalmanUpdate(measurement: number): number {
    // 卡尔曼增益：K = P * H^T / (H * P * H^T + R)
    // 这里 H=1，所以 K = P / (P + R)
    const K = this.kalmanState.p / (this.kalmanState.p + this.kalmanState.r)

    // 更新估计值：x_k = x_k + K * (z_k - H * x_k)
    // 这里 H=1，所以 x_k = x_k + K * (z_k - x_k)
    this.kalmanState.x = this.kalmanState.x + K * (measurement - this.kalmanState.x)

    // 更新误差：P_k = (1 - K * H) * P_k
    // 这里 H=1，所以 P_k = (1 - K) * P_k
    this.kalmanState.p = (1 - K) * this.kalmanState.p

    return this.kalmanState.x
  }

  /**
   * 更新自适应阈值
   */
  private updateAdaptiveThreshold(volume: number): void {
    if (!this.config.enableAdaptiveThreshold) {
      return
    }

    // 添加到窗口
    this.adaptiveThreshold.window.push(volume)

    // 保持窗口大小
    if (this.adaptiveThreshold.window.length > this.config.adaptiveWindow!) {
      this.adaptiveThreshold.window.shift()
    }

    // 计算动态阈值：平均值 + 1个标准差
    if (this.adaptiveThreshold.window.length === this.config.adaptiveWindow!) {
      const mean = this.adaptiveThreshold.window.reduce((a, b) => a + b, 0) / this.adaptiveThreshold.window.length
      const variance = this.adaptiveThreshold.window.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / this.adaptiveThreshold.window.length
      const stdDev = Math.sqrt(variance)

      // 阈值 = 均值 + 0.5 * 标准差
      const dynamicThreshold = mean + 0.5 * stdDev
      this.adaptiveThreshold.current = Math.max(dynamicThreshold, this.config.minThreshold!)
    }
  }

  /**
   * 更新语音状态检测
   */
  private updateSpeechState(volume: number): void {
    // 添加到语音检测窗口
    this.speechState.speechWindow.push(volume)
    if (this.speechState.speechWindow.length > this.config.speechDetectionWindow!) {
      this.speechState.speechWindow.shift()
    }

    // 计算窗口内的平均音量
    const avgVolume = this.speechState.speechWindow.reduce((a, b) => a + b, 0) / this.speechState.speechWindow.length

    // 判断是否在说话
    const wasSpeaking = this.speechState.isSpeaking
    this.speechState.isSpeaking = avgVolume > this.config.speechThreshold!

    // 状态转换检测
    if (this.speechState.isSpeaking && !wasSpeaking) {
      // 从沉默/停顿转为说话：重置停顿窗口
      this.speechState.isPaused = false
      this.speechState.pauseWindow = []
      this.speechState.mouthValueDuringPause = 0
    } else if (!this.speechState.isSpeaking && wasSpeaking) {
      // 从说话转为沉默：开始停顿检测
      this.speechState.isPaused = true
    }

    // 停顿窗口处理
    if (this.speechState.isPaused) {
      this.speechState.pauseWindow.push(volume)
      if (this.speechState.pauseWindow.length > this.config.pauseDetectionWindow!) {
        this.speechState.pauseWindow.shift()
      }

      // 如果停顿窗口内音量持续很低，认为进入沉默状态
      const pauseAvg = this.speechState.pauseWindow.reduce((a, b) => a + b, 0) / this.speechState.pauseWindow.length
      if (pauseAvg < this.config.speechThreshold! * 0.5) {
        // 真正的沉默，不是短暂停顿
        this.speechState.isPaused = false
      }
    }
  }

  async connect(audioElement: HTMLAudioElement): Promise<void> {
    try {
      if (typeof window === 'undefined') {
        logger.warn('[AdvancedLipSyncEngine] Running in SSR mode')
        return
      }

      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      this.analyser = this.audioContext.createAnalyser()
      this.analyser.fftSize = 512
      this.analyser.smoothingTimeConstant = 0.5

      const bufferLength = this.analyser.frequencyBinCount
      this.dataArray = new Uint8Array(bufferLength)

      this.source = this.audioContext.createMediaElementSource(audioElement)
      this.source.connect(this.analyser)
      this.analyser.connect(this.audioContext.destination)

      logger.info('[AdvancedLipSyncEngine] ✅ 已连接音频元素')
      this.startAnalysis()
    } catch (error) {
      logger.error('[AdvancedLipSyncEngine] 连接失败:', error)
      throw error
    }
  }

  private startAnalysis(): void {
    if (this.animationId !== null) return

    const analyze = () => {
      if (!this.analyser || !this.dataArray) return

      this.analyser.getByteFrequencyData(this.dataArray)

      // 计算RMS音量
      let sum = 0
      for (let i = 0; i < this.dataArray.length; i++) {
        sum += this.dataArray[i] * this.dataArray[i]
      }
      const rms = Math.sqrt(sum / this.dataArray.length)
      const volume = rms / 255

      this.processVolume(volume)

      this.animationId = requestAnimationFrame(analyze)
    }

    this.animationId = requestAnimationFrame(analyze)
  }

  /**
   * 处理音量值（核心逻辑）
   */
  private processVolume(volume: number): void {
    // 1. 更新语音状态检测
    this.updateSpeechState(volume)

    // 2. 更新自适应阈值
    this.updateAdaptiveThreshold(volume)

    // 3. 应用阈值：低于阈值时设为0
    if (volume < this.adaptiveThreshold.current) {
      volume = 0
    }

    // 4. 应用非线性曲线映射
    volume = this.applyNonLinearCurve(volume)

    // 5. 应用基础音量乘数
    volume = volume * this.config.baseVolumeMultiplier!

    // 6. 卡尔曼滤波预测和更新
    if (this.config.enableSmoothing) {
      this.kalmanPredict()
      volume = this.kalmanUpdate(volume)
    }

    // 7. 限制在 [0, 1] 范围
    volume = Math.max(0, Math.min(1, volume))

    // 8. 根据语音状态调整嘴巴行为
    if (this.speechState.isSpeaking) {
      // 正在说话：正常更新嘴巴
      this.speechState.mouthValueDuringPause = volume
      this.onUpdate(volume)
    } else if (this.speechState.isPaused) {
      // 短暂停顿：嘴巴逐渐闭合
      this.speechState.mouthValueDuringPause *= (1 - this.config.pauseCloseSpeed!)
      this.onUpdate(this.speechState.mouthValueDuringPause)
    } else {
      // 沉默状态：嘴巴完全闭合
      this.speechState.mouthValueDuringPause = 0
      this.onUpdate(0)
    }
  }

  /**
   * 基于预计算音量的播放（带时间补偿）
   */
  startWithVolumes(volumes: number[], sampleRate: number = 50): void {
    logger.info('[AdvancedLipSyncEngine] ========== startWithVolumes 被调用 ==========')
    logger.info(`采样点数: ${volumes.length}`)
    logger.info(`采样率: ${sampleRate} Hz`)
    logger.info(`音量范围: [${Math.min(...volumes).toFixed(3)}, ${Math.max(...volumes).toFixed(3)}]`)

    this.volumes = volumes
    this.volumesSampleRate = sampleRate
    this.volumesStartTime = performance.now()

    logger.info('[AdvancedLipSyncEngine] 开始动画循环（带时间补偿）')
    this.startVolumesAnimation()
  }

  /**
   * 预计算音量的动画循环（高级版）
   */
  private startVolumesAnimation(): void {
    let frameCount = 0
    let lastLogTime = 0
    const timeOffset = this.config.timeCompensationFrames! / this.volumesSampleRate * 1000 // 转换为毫秒

    const animate = () => {
      const currentTime = performance.now()
      const elapsed = (currentTime - this.volumesStartTime) + timeOffset // 时间补偿

      // 计算当前应该播放的采样点索引
      const sampleIndex = Math.floor(elapsed * this.volumesSampleRate / 1000)

      if (sampleIndex >= this.volumes.length) {
        logger.info('[AdvancedLipSyncEngine] ========== 预计算音量播放完成 ==========')
        this.onUpdate(0)
        this.volumesAnimationId = null
        this.kalmanState.x = 0 // 重置卡尔曼滤波
        return
      }

      // 获取当前音量
      let volume = this.volumes[sampleIndex]

      // 应用高级处理流程
      this.processVolume(volume)

      // 每 60 帧记录一次日志（约 1 秒）
      frameCount++
      if (currentTime - lastLogTime > 1000) {
        logger.debug(`[AdvancedLipSyncEngine] 帧: ${frameCount}, 索引: ${sampleIndex}/${this.volumes.length}`)
        lastLogTime = currentTime
      }

      this.volumesAnimationId = requestAnimationFrame(animate)
    }

    this.volumesAnimationId = requestAnimationFrame(animate)
  }

  stopVolumes(): void {
    if (this.volumesAnimationId) {
      cancelAnimationFrame(this.volumesAnimationId)
      this.volumesAnimationId = null
      logger.info('[AdvancedLipSyncEngine] 预计算音量播放已停止')
    }
  }

  disconnect(): void {
    if (this.animationId) {
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

    logger.info('[AdvancedLipSyncEngine] 已断开连接')
  }
}
