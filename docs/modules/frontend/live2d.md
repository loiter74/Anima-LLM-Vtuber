# Live2D 集成

> pixi-live2d-display 的集成和使用

---

## 目录

1. [Live2D 模型加载](#live2d-模型加载)
2. [表情控制](#表情控制)
3. [唇同步](#唇同步)
4. [架构设计](#架构设计)

---

## Live2D 模型加载

### Live2DService

```typescript
// frontend/features/live2d/services/Live2DService.ts
import { Live2DModel } from 'pixi-live2d-display'
import * as PIXI from 'pixi.js'

export class Live2DService {
  private model: Live2DModel | null = null
  private app: PIXI.Application

  async loadModel(modelPath: string) {
    // 暴露 PIXI
    window.PIXI = PIXI

    // 创建 PIXI 应用
    this.app = new PIXI.Application()
    await this.app.init({
      width: 1200,
      height: 1200,
      view: canvas,
      backgroundColor: 0xFFFFFF
    })

    // 加载模型
    this.model = await Live2DModel.from(modelPath)
    this.app.stage.addChild(this.model)

    // 设置锚点
    this.model.anchor.set(0.5, 0.5)

    // 设置位置
    this.model.x = canvasWidth / 2
    this.model.y = canvasHeight / 2

    // 设置缩放
    this.model.scale.set(0.5)
  }
}
```

---

## 表情控制

### 设置表情

```typescript
// 通过索引设置
await model.expression(3)  // happy

// 随机表情
await model.expression()

// 使用 emotion map
const expressionMap = {
  happy: 3,
  sad: 1,
  angry: 2,
  surprised: 4,
  neutral: 0
}
await model.expression(expressionMap['happy'])
```

### 表情时间轴

```typescript
// frontend/features/live2d/services/ExpressionTimeline.ts
export class ExpressionTimeline {
  private segments: TimelineSegment[]
  private onExpressionChange: (emotion: string) => void

  play(segments: TimelineSegment[], duration: number) {
    this.segments = segments.sort((a, b) => a.time - b.time)
    this.startTime = performance.now() / 1000

    // 开始动画循环
    this.startAnimationLoop()
  }

  private startAnimationLoop() {
    const loop = () => {
      const currentTime = performance.now() / 1000
      const elapsed = currentTime - this.startTime

      // 查找当前时间的表情
      const segment = this.segments.find(seg =>
        elapsed >= seg.time && elapsed < seg.time + seg.duration
      )

      if (segment && segment.emotion !== this.currentEmotion) {
        this.onExpressionChange(segment.emotion)
        this.currentEmotion = segment.emotion
      }

      requestAnimationFrame(loop)
    }

    requestAnimationFrame(loop)
  }
}
```

---

## 唇同步

### LipSyncEngine

```typescript
// frontend/features/live2d/services/LipSyncEngine.ts
export class LipSyncEngine {
  private onUpdate: (value: number) => void
  private updateInterval: number
  private currentVolume: number = 0

  constructor(
    onUpdate: (value: number) => void,
    options: {
      updateInterval: number  // ms
      smoothingFactor: number  // 0.0 - 1.0
      volumeMultiplier: number
    }
  ) {
    this.onUpdate = onUpdate
    this.updateInterval = options.updateInterval
    this.smoothingFactor = options.smoothingFactor
    this.volumeMultiplier = options.volumeMultiplier
  }

  startWithVolumes(volumes: number[], sampleRate: number) {
    // 每 20ms 更新一次（50Hz 采样）
    const intervalMs = 1000 / sampleRate

    this.volumes = volumes
    this.sampleRate = sampleRate

    this.intervalId = setInterval(() => {
      const index = Math.floor((Date.now() - this.startTime) / intervalMs)
      const targetValue = this.volumes[index]

      // 平滑处理
      this.currentVolume = this.smoothingFactor * targetValue +
                         (1 - this.smoothingFactor) * this.currentVolume

      this.onUpdate(this.currentVolume * this.volumeMultiplier)
    }, this.updateInterval)
  }

  stop() {
    if (this.intervalId) {
      clearInterval(this.intervalId)
      this.intervalId = null
    }
  }
}
```

### 使用示例

```typescript
// 1. 创建唇同步引擎
const lipSyncEngine = new LipSyncEngine(
  (value: number) => {
    // 更新嘴部参数
    const coreModel = model.internalModel.coreModel
    const mouthIndex = coreModel.getParameterIndex('ParamMouthOpenY')
    coreModel.setParameterValueByIndex(mouthIndex, value)
  },
  {
    updateInterval: 33,  // ~30fps
    smoothingFactor: 0.3,
    volumeMultiplier: 2.5
  }
)

// 2. 开始播放时启动
lipSyncEngine.startWithVolumes(volumes, 50)

// 3. 音频结束时停止
lipSyncEngine.stop()
```

---

## 架构设计

### Live2D 服务层

```
┌─────────────────────────────────────────────────────────────┐
│                    useLive2D Hook                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ - canvasRef (useRef)                                      │  │
│  │ - serviceRef (useRef)                                    │  │
│  │ - setExpression (callback)                               │  │
│  │ - playAudioWithExpressions (method)                      │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                  Live2DService                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ - loadModel()                                              │  │
│  │ - setExpression()                                          │  │
│  │ - setMouthOpen()                                            │  │
│  │ - playTimeline()                                            │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│              pixi-live2d-display                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ - Live2DModel                                              │  │
│  │   - expression() - 设置表情                             │  │
│  │   - motion() - 播放动作                                 │  │
│  │ - PIXI.Application - 渲染引擎                          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 总结

### Live2D 集成关键点

1. **pixi-live2d-display**：Live2D 渲染引擎
2. **ExpressionTimeline**：时间轴表情同步
3. **LipSyncEngine**：音频驱动的唇同步
4. **useLive2D Hook**：React 封装层

---

**最后更新**: 2026-02-28
