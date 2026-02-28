# Live2D 唇同步诊断工具

> 在浏览器控制台运行这些命令来诊断问题

## 快速诊断步骤

### 1. 检查 Live2D 服务是否加载

在浏览器控制台运行：

```javascript
// 检查 Live2D 服务实例
const service = window.__live2dService
console.log('Live2D 服务实例:', service)

if (!service) {
  console.error('❌ Live2D 服务未加载！请等待模型加载完成')
} else {
  console.log('✅ Live2D 服务已加载')
}
```

### 2. 检查模型参数

```javascript
// 获取 Live2D 服务实例
const service = window.__live2dService
if (!service) {
  console.error('请先等待模型加载')
} else {
  const model = service.model
  const internalModel = model?.internalModel
  const coreModel = internalModel?.coreModel

  console.log('模型信息:')
  console.log('- model:', model)
  console.log('- internalModel:', internalModel)
  console.log('- coreModel:', coreModel)

  if (coreModel) {
    // 列出所有参数
    const paramCount = coreModel.getParameterCount()
    console.log(`\n总参数数: ${paramCount}`)

    // 查找所有包含 "Mouth" 或 "Param" 的参数
    console.log('\n🔍 查找嘴部相关参数:')
    const mouthParams = []
    for (let i = 0; i < Math.min(paramCount, 50); i++) {
      try {
        const id = coreModel.getParameterId(i)
        const value = coreModel.getParameterValueByIndex(i)

        if (id.includes('Mouth') || id.includes('ParamMouth') || id.includes('ParamEye')) {
          mouthParams.push({ index: i, id, value })
          console.log(`  [${i}] ${id} = ${value.toFixed(3)}`)
        }
      } catch (e) {
        // 忽略错误
      }
    }

    if (mouthParams.length === 0) {
      console.warn('⚠️ 未找到任何嘴部参数！')
      console.log('\n前 20 个参数:')
      for (let i = 0; i < Math.min(paramCount, 20); i++) {
        try {
          const id = coreModel.getParameterId(i)
          const value = coreModel.getParameterValueByIndex(i)
          console.log(`  [${i}] ${id} = ${value.toFixed(3)}`)
        } catch (e) {
          // 忽略
        }
      }
    }
  } else {
    console.error('❌ coreModel 未找到！')
  }
}
```

### 3. 测试嘴部参数设置

```javascript
// 测试设置嘴部参数
const service = window.__live2dService
if (!service) {
  console.error('请先等待模型加载')
} else {
  const model = service.model
  const internalModel = model?.internalModel
  const coreModel = internalModel?.coreModel

  if (coreModel) {
    const mouthIndex = coreModel.getParameterIndex('ParamMouthOpenY')
    console.log(`\nParamMouthOpenY 索引: ${mouthIndex}`)

    if (mouthIndex >= 0) {
      const currentValue = coreModel.getParameterValueByIndex(mouthIndex)
      console.log(`当前值: ${currentValue.toFixed(3)}`)

      // 测试设置不同的值
      console.log('\n🧪 测试设置不同值:')

      const testValues = [0.0, 0.5, 1.0]
      testValues.forEach((val, i) => {
        setTimeout(() => {
          coreModel.setParameterValueByIndex(mouthIndex, val)
          const newValue = coreModel.getParameterValueByIndex(mouthIndex)
          console.log(`  [${i}] 设置为 ${val.toFixed(1)} → 实际值: ${newValue.toFixed(3)}`)

          // 如果看不到变化，可能需要手动触发模型更新
          if (model.internalModel?.coreModel) {
            model.internalModel.coreModel.update()
            model.internalModel.model.update()
          }
        }, i * 1000)
      })

      console.log('\n⏳ 请观察模型嘴巴，应该在接下来 3 秒内看到变化')
      console.log('   - 0.0 (闭合)')
      console.log('   - 0.5 (半开)')
      console.log('   - 1.0 (全开)')
    } else {
      console.error('❌ ParamMouthOpenY 参数未找到！')
      console.log('\n可能的原因:')
      console.log('1. 模型文件不包含此参数')
      console.log('2. 参数名称不同（可能 ParamMouthOpenY 不是正确的名称）')
      console.log('3. cubism4 版本问题')
    }
  }
}
```

### 4. 检查音量包络数据

```javascript
// 监听音量包络数据
let lastVolumesLogTime = 0

// 拦截 setMouthOpen 调用
const originalSetMouthOpen = window.__live2dService?.setMouthOpen

if (originalSetMouthOpen) {
  window.__live2dService.setMouthOpen = function(value) {
    const now = performance.now()

    // 每 1 秒记录一次
    if (now - lastVolumesLogTime > 1000 || lastVolumesLogTime === 0) {
      console.log(`\n📊 嘴部参数更新: ${value.toFixed(3)}`)
      console.log(`   时间: ${new Date().toLocaleTimeString()}`)
      lastVolumesLogTime = now
    }

    return originalSetMouthOpen.call(this, value)
  }

  console.log('✅ 已拦截 setMouthOpen 调用，现在将显示所有更新')
} else {
  console.error('❌ setMouthOpen 方法未找到')
}
```

### 5. 检查事件流

```javascript
// 监听所有 Live2D 相关事件
const events = []

window.addEventListener('audio:with:expression', (e) => {
  const detail = e.detail
  console.log('\n📦 收到 audio_with_expression 事件:')
  console.log('  - 音频数据长度:', detail.audio_data?.length)
  console.log('  - 音量采样点数:', detail.volumes?.length)
  console.log('  - 表情片段数:', detail.expressions?.segments?.length)
  console.log('  - 总时长:', detail.expressions?.total_duration, '秒')

  // 记录最近的事件
  events.push({ type: 'audio_with_expression', time: Date.now(), detail })

  if (detail.volumes?.length > 0) {
    const minVol = Math.min(...detail.volumes).toFixed(3)
    const maxVol = Math.max(...detail.volumes).toFixed(3)
    console.log(`  - 音量范围: [${minVol}, ${maxVol}]`)
  }
})

console.log('✅ 已监听 audio:with:expression 事件')

// 查看记录的事件
window.showLive2DEvents = function() {
  console.log('\n📝 最近的事件记录:')
  events.slice(-5).forEach((evt, i) => {
    console.log(`  [${i}] ${evt.type} - ${new Date(evt.time).toLocaleTimeString()}`)
  })
}
```

---

## 常见问题和解决方案

### 问题 1: "ParamMouthOpenY 参数未找到"

**可能原因**：
1. 模型文件不包含此参数
2. cubism4 版本参数系统不同

**解决方案**：

```javascript
// 查找所有可用参数
const service = window.__live2dService
const coreModel = service?.model?.internalModel?.coreModel

if (coreModel) {
  const paramCount = coreModel.getParameterCount()
  const allParams = []

  for (let i = 0; i < paramCount; i++) {
    try {
      const id = coreModel.getParameterId(i)
      allParams.push({ index: i, id })
    } catch (e) {
      // 忽略
    }
  }

  console.log('所有可用参数:', allParams)

  // 尝试查找类似的参数
  const mouthParams = allParams.filter(p =>
    p.id.toLowerCase().includes('mouth') ||
    p.id.toLowerCase().includes('lip') ||
    p.id.toLowerCase().includes('param')
  )

  console.log('嘴部相关参数:', mouthParams)
}
```

### 问题 2: 参数设置了但模型不更新

**可能原因**：
1. 需要手动触发模型更新
2. cubism4 版本需要特殊处理

**解决方案**：

```javascript
// 强制更新模型
const service = window.__live2dService
if (service?.model) {
  const model = service.model

  // 尝试不同的更新方法
  console.log('尝试更新模型...')

  // 方法 1: update()
  if (typeof model.update === 'function') {
    model.update()
    console.log('✅ 已调用 model.update()')
  }

  // 方法 2: internalModel.coreModel.update()
  if (model?.internalModel?.coreModel) {
    model.internalModel.coreModel.update()
    console.log('✅ 已调用 coreModel.update()')
  }

  // 方法 3: model.internalModel.model.update()
  if (model?.internalModel?.model) {
    model.internalModel.model.update()
    console.log('✅ 已调用 model.update()')
  }
}
```

### 问题 3: 嘴部动作幅度太小

**解决方案**：

```javascript
// 手动设置更大的嘴部值
const service = window.__live2dService
const coreModel = service?.model?.internalModel?.coreModel

if (coreModel) {
  const mouthIndex = coreModel.getParameterIndex('ParamMouthOpenY')

  if (mouthIndex >= 0) {
    // 设置为 1.0（最大值）
    coreModel.setParameterValueByIndex(mouthIndex, 1.0)

    // 强制更新
    if (service.model?.internalModel?.coreModel) {
      service.model.internalModel.coreModel.update()
    }

    console.log('✅ 已设置嘴部为最大值 1.0')
  }
}
```

---

## 完整诊断脚本

将以下代码复制到浏览器控制台，一次性运行所有诊断：

```javascript
(function live2DDiagnostic() {
  console.log('\n========================================')
  console.log('🔍 Live2D 唇同步诊断工具')
  console.log('========================================\n')

  const service = window.__live2dService

  // 1. 检查服务
  console.log('1️⃣ 检查 Live2D 服务')
  if (!service) {
    console.error('   ❌ Live2D 服务未加载！请等待模型加载完成')
    return
  }
  console.log('   ✅ Live2D 服务已加载')

  // 2. 检查模型
  console.log('\n2️⃣ 检查模型')
  const model = service.model
  const internalModel = model?.internalModel
  const coreModel = internalModel?.coreModel

  if (!model || !internalModel || !coreModel) {
    console.error('   ❌ 模型未正确加载')
    console.log('   - model:', model)
    console.log('   - internalModel:', internalModel)
    console.log('   - coreModel:', coreModel)
    return
  }
  console.log('   ✅ 模型已加载')

  // 3. 列出参数
  console.log('\n3️⃣ 列出所有参数（前 20 个）')
  const paramCount = coreModel.getParameterCount()
  console.log(`   总参数数: ${paramCount}`)

  for (let i = 0; i < Math.min(paramCount, 20); i++) {
    try {
      const id = coreModel.getParameterId(i)
      const value = coreModel.getParameterValueByIndex(i)
      console.log(`   [${i}] ${id} = ${value.toFixed(3)}`)
    } catch (e) {
      // 忽略
    }
  }

  // 4. 查找嘴部参数
  console.log('\n4️⃣ 查找嘴部参数')
  const mouthIndex = coreModel.getParameterIndex('ParamMouthOpenY')
  console.log(`   ParamMouthOpenY 索引: ${mouthIndex}`)

  if (mouthIndex >= 0) {
    const currentValue = coreModel.getParameterValueByIndex(mouthIndex)
    console.log(`   当前值: ${currentValue.toFixed(3)}`)
    console.log('   ✅ ParamMouthOpenY 参数存在')
  } else {
    console.error('   ❌ ParamMouthOpenY 参数未找到！')

    // 列出所有参数以便查找
    console.log('\n   🔍 查找所有包含 "Mouth" 的参数:')
    for (let i = 0; i < Math.min(paramCount, 50); i++) {
      try {
        const id = coreModel.getParameterId(i)
        if (id.toLowerCase().includes('mouth')) {
          const value = coreModel.getParameterValueByIndex(i)
          console.log(`     [${i}] ${id} = ${value.toFixed(3)}`)
        }
      } catch (e) {
        // 忽略
      }
    }
  }

  // 5. 测试嘴部参数
  if (mouthIndex >= 0) {
    console.log('\n5️⃣ 测试嘴部参数（3 秒）')
    const testValues = [0.0, 0.5, 1.0]

    testValues.forEach((val, i) => {
      setTimeout(() => {
        coreModel.setParameterValueByIndex(mouthIndex, val)
        const newValue = coreModel.getParameterValueByIndex(mouthIndex)
        console.log(`   [${i}] 设置为 ${val.toFixed(1)} → 实际: ${newValue.toFixed(3)} ${val === 1.0 ? '✅' : ''}`)

        // 强制更新
        if (service.model?.internalModel?.coreModel) {
          service.model.internalModel.coreModel.update()
        }
      }, i * 1000)
    })

    console.log('   ⏳ 请观察模型嘴巴，应该在 3 秒内看到变化')
  }

  console.log('\n========================================')
  console.log('📋 诊断完成')
  console.log('========================================\n')

  return {
    service,
    model,
    coreModel,
    mouthIndex
  }
})()
```

---

## 下一步

运行诊断脚本后，请将控制台输出告诉我，我会根据输出帮你解决问题。

**如果参数存在但看不到变化**：
- 可能是模型渲染问题
- 需要强制更新模型

**如果参数不存在**：
- 需要查找正确的参数名称
- 或者模型文件可能不完整

**如果完全没有调用 setMouthOpen**：
- 需要检查事件流
- 确认音频是否正确播放
