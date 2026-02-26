# Live2D 唇同步功能测试指南

## 功能概述

唇同步功能让 Live2D 角色在播放语音时能够同步张嘴说话，提升交互真实感。

## 实现原理

```
音频文件 → AudioAnalyzer (后端) → 音量包络 (50Hz) → WebSocket → 前端
                                                              ↓
                              LipSyncEngine → Live2DService.setMouthOpen()
                                                              ↓
                                        Live2D Model (ParamMouthOpenY)
```

## 配置说明

### 前端配置 (`config/features/live2d.yaml`)

```yaml
lip_sync:
  enabled: true           # 是否启用唇同步
  sensitivity: 1.0        # 灵敏度 (0.5 - 2.0)
  smoothing: 0.3          # 平滑系数 (0.0 - 1.0)，越小越平滑
  min_threshold: 0.05     # 最小音量阈值，过滤背景噪音
  max_value: 1.0          # 最大嘴部张开度
  use_mouth_form: false   # 是否同时控制嘴形
```

### 参数调优建议

| 问题 | 调整方案 |
|------|---------|
| 嘴部动作太小 | 增加 `sensitivity` 到 1.5-2.0 |
| 嘴部动作太大 | 减少 `sensitivity` 到 0.7-0.8 |
| 嘴部抖动明显 | 增加 `smoothing` 到 0.5-0.7 |
| 背景噪音触发 | 增加 `min_threshold` 到 0.1-0.15 |
| 动作延迟 | 减少 `smoothing` 到 0.1-0.2 |

## 测试步骤

### 1. 启动服务

```bash
# 启动后端和前端
.\scripts\start.ps1
```

### 2. 发送语音消息

在前端界面中：
- 点击麦克风按钮开始录音
- 说一段话
- 再次点击按钮停止录音
- 观察 Live2D 模型播放语音时的嘴部动作

### 3. 验证要点

- ✅ **说话时嘴巴张开**：音频播放期间，模型嘴巴应该有节奏地开合
- ✅ **停顿时嘴巴闭合**：音频间隙或静音时，嘴巴应该闭合
- ✅ **动作流畅**：嘴部动作应该平滑，不应该有明显的抖动
- ✅ **同步准确**：嘴部动作应该与语音节奏基本同步（延迟 < 100ms）

## 常见问题排查

### 问题 1：嘴部不动作

**可能原因**：
1. 唇同步未启用
2. 音量包络数据未正确传输
3. Live2D 模型不支持 `ParamMouthOpenY` 参数

**排查方法**：
```javascript
// 在浏览器控制台检查
window.addEventListener('audio:with:expression', (e) => {
  console.log('收到音频事件:', e.detail)
  // 检查 volumes 数组是否有数据
})

// 检查 Live2D 参数
const live2dService = serviceRef.current
console.log('嘴部参数索引:', live2dService.mouthParamIndex)
```

### 问题 2：嘴部动作幅度太小

**解决方案**：
1. 增加 `sensitivity` 到 1.5-2.0
2. 检查音量包络数据是否正常
3. 确认 `max_value` 设置为 1.0

### 问题 3：嘴部抖动严重

**解决方案**：
1. 增加 `smoothing` 到 0.5-0.7
2. 增加 `min_threshold` 过滤低音量
3. 减少 `sensitivity`

### 问题 4：动作与语音不同步

**可能原因**：
- 网络延迟
- 音频加载时间
- 浏览器音频播放延迟

**解决方案**：
- 使用本地 TTS 服务减少延迟
- 检查网络连接
- 调整 LipSyncEngine 的 `smoothingFactor`

## 性能监控

### 开启调试日志

```typescript
// 在 Live2DService.ts 中
logger.debug('[Live2DService] 嘴部参数值:', this.currentMouthValue)
```

### 性能指标

- **更新频率**：~30fps (每 33ms 更新一次)
- **CPU 占用**：< 1%（单核）
- **内存占用**：可忽略不计

## 高级配置

### 使用嘴形控制（更自然）

```yaml
lip_sync:
  use_mouth_form: true   # 启用嘴形控制
```

**注意**：启用嘴形控制会：
- ✅ 嘴部动作更自然
- ⚠️ 略微增加性能开销
- ⚠️ 需要模型支持 `ParamMouthForm` 参数

### 自定义灵敏度曲线

```typescript
// 在 LipSyncEngine.ts 中自定义
const applyCurve = (value: number) => {
  // 非线性映射，让小音量也有明显动作
  return Math.pow(value, 0.7)
}
```

## 技术细节

### Live2D 参数说明

- **ParamMouthOpenY**：控制嘴部上下张开度 (0.0 - 1.0)
- **ParamMouthForm**：控制嘴部形状 (0.0 - 1.0)

### 音频分析流程

1. **后端**：使用 `pydub` 分析音频文件
2. **采样率**：50 Hz (每 20ms 一个采样点)
3. **输出**：归一化音量数组 [0.0, 1.0]

### 平滑处理算法

```typescript
// 指数移动平均 (EMA)
smoothed = current * smoothing + new * (1 - smoothing)
```

## 参考资料

- [Live2D Cubism SDK 文档](https://docs.live2d.com/)
- [Web Audio API 规范](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)
- [pydub 音频处理文档](http://pydub.com/)

## 更新日志

### 2025-02-27
- ✅ 实现 `setMouthOpen` 方法
- ✅ 添加配置化参数系统
- ✅ 优化 LipSyncEngine 性能
- ✅ 添加参数缓存和平滑处理
