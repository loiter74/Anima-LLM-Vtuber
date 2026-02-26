# Neuro-sama 风格 Live2D 模型设置指南

## 概述

Neuro-sama 最初使用的是 **Epsilon** 模型（Live2D 官方免费模型）。本指南将帮助你设置相同风格的模型。

## 方案对比

| 模型 | 特点 | 推荐度 | 获取难度 |
|------|------|--------|----------|
| **Epsilon** | Neuro-sama 最初使用的模型，可爱风格 | ⭐⭐⭐⭐⭐ | 简单 |
| **Hiyori** | 官方免费模型，成熟稳定 | ⭐⭐⭐⭐⭐ | 简单 |
| **Haru** | 当前项目中已安装 | ⭐⭐⭐ | 已安装 |

## 快速开始（推荐 Hiyori）

### 步骤 1: 下载 Live2D Cubism SDK

1. 访问 Live2D 官方网站: https://www.live2d.com/download/cubism-sdk/download-web/
2. 注册账号（免费）
3. 下载 **Cubism SDK for Web** (最新版本)
4. 解压下载的 ZIP 文件

### 步骤 2: 提取 Hiyori 模型

解压后的 SDK 文件结构:
```
CubismSdkForWeb-4-r.X/
├── Sample/
│   ├── Hiyori/              ← 这是 Hiyori 模型文件夹
│   │   ├── Hiyori.model3.json
│   │   ├── Hiyori.moc3
│   │   ├── Hiyori2048/
│   │   │   └── texture_00.png
│   │   ├── motions/
│   │   └── expressions/
│   └── Epsilon/              ← 这也是可选的模型
│       ├── Epsilon.model3.json
│       └── ...
```

### 步骤 3: 复制到项目

将 `Sample/Hiyori` 文件夹复制到：
```
frontend/public/live2d/hiyori/
```

**Windows PowerShell**:
```powershell
# 从 SDK 解压位置复制（请根据实际路径调整）
Copy-Item "C:\Users\YourName\Downloads\CubismSdkForWeb-4-r.X\Sample\Hiyori" `
          "C:\Users\30262\Project\Anima\frontend\public\live2d\hiyori" -Recurse
```

### 步骤 4: 更新配置

编辑 `config/features/live2d.yaml`:
```yaml
model:
  path: "/live2d/hiyori/hiyori.model3.json"  # 改为 Hiyori
  scale: 0.5
  position:
    x: 0
    y: 0
```

### 步骤 5: 更新情感映射

Hiyori 模型的 motion 索引可能不同，根据实际文件调整 `emotion_map`:
```yaml
emotion_map:
  happy: 0      # 根据实际 motion 文件调整
  sad: 1
  angry: 2
  surprised: 3
  neutral: 0
  thinking: 4
```

### 步骤 6: 重启服务

```bash
# 重启前端
.\scripts\stop.ps1
.\scripts\start.ps1 -SkipBackend
```

## 使用 Epsilon 模型（Neuro-sama 原版）

如果你想使用 Neuro-sama 最初使用的 Epsilon 模型：

### 步骤 1-2: 同上（下载 SDK）

### 步骤 3: 复制 Epsilon 模型

```powershell
Copy-Item "C:\Users\YourName\Downloads\CubismSdkForWeb-4-r.X\Sample\Epsilon" `
          "C:\Users\30262\Project\Anima\frontend\public\live2d\epsilon" -Recurse
```

### 步骤 4: 更新配置

```yaml
model:
  path: "/live2d/epsilon/epsilon.model3.json"  # 改为 Epsilon
  scale: 0.5
  position:
    x: 0
    y: 0
```

## 验证模型加载成功

打开浏览器控制台，应该看到：
```
[Live2DService] ✅ All libraries loaded
[Live2DService] 正在加载模型: /live2d/hiyori/hiyori.model3.json
[Live2DService] 模型加载成功
```

## 常见问题

### Q: 模型加载后不显示
- 检查控制台是否有错误
- 确认 `scale` 和 `position` 参数
- 尝试调整 `scale` 值（0.3 - 0.8）

### Q: "Could not find Cubism 4 runtime"
- 确保 `live2dcubismcore.js` 已放置在 `frontend/public/`
- 检查 `frontend/app/layout.tsx` 中的 Script 标签

### Q: 模型表情不工作
- 检查 `emotion_map` 中的索引是否与模型文件匹配
- 查看 `motions/` 文件夹中的实际 motion 文件

## 模型文件清单

Hiyori 模型应该包含以下文件：
```
hiyori/
├── hiyori.model3.json    # 模型配置文件
├── hiyori.moc3           # 模型文件
├── hiyori2048/           # 纹理资源
│   └── texture_00.png
├── motions/              # 动作文件
│   └── ...
└── expressions/          # 表情文件（可选）
    └── ...
```

## 在线资源

- **Live2D 官方**: https://www.live2d.com/
- **Cubism SDK 下载**: https://www.live2d.com/download/cubism-sdk/download-web/
- **GitHub - awesome-digital-human-live2d**: https://github.com/wan-h/awesome-digital-human-live2d

## 下一步

模型加载成功后：
1. 测试表情系统是否工作
2. 测试唇同步功能
3. 根据需要调整模型大小和位置
